# -*- coding: utf-8 -*-
"""
离线网页保存器（PySide6 + QtWebEngine + SingleFile）
左侧输入网址与保存控制，右侧直接浏览网页；保存前自动关闭网页弹窗。
"""
import datetime
import io
import json
import os
import re
import sys
import traceback

from PySide6.QtCore import QEventLoop, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                     QWebEngineSettings)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QSplitter, QTextEdit, QToolButton,
                               QVBoxLayout, QWidget)

APP_NAME = "离线网页保存器"
APP_VER = "2.0"
HERE = os.path.dirname(os.path.abspath(__file__))


def res_path(*parts):
    base = getattr(sys, "_MEIPASS", HERE)
    return os.path.join(base, *parts)


def lib_dir():
    for cand in (res_path("sflib"), os.path.join(HERE, "sflib"), os.path.join(HERE, "lib")):
        if os.path.isfile(os.path.join(cand, "single-file.js")):
            return cand
    return None


# ------------------------------------------------------------------ 清理弹窗脚本
CLEAN_JS = r"""
(function(){
  var removed = [], vw = window.innerWidth, vh = window.innerHeight;
  var NAME_RE = /(modal|popup|dialog|mask|overlay|lightbox|layer|consent|cookie|subscribe|banner)/i;
  function nameHit(el){
    var s = (el.id || '') + ' ' + (el.className && el.className.baseVal !== undefined
        ? el.className.baseVal : (el.className || ''));
    try { s += ' ' + (el.getAttribute('data-role') || '') + ' ' + (el.getAttribute('aria-label') || ''); } catch(e){}
    return NAME_RE.test(s);
  }
  function kill(el){
    try { if (el && el.parentNode) { el.parentNode.removeChild(el); removed.push(el.tagName); } } catch(e){}
  }
  // 1. 语义化弹窗
  var list = document.querySelectorAll(
    'dialog[open],[role="dialog"],[role="alertdialog"],[aria-modal="true"],.modal-backdrop,' +
    '.el-overlay,.ant-modal-mask,.v-modal,.layui-layer-shade,.weui-mask');
  for (var i = 0; i < list.length; i++) kill(list[i]);
  // 2. 名称命中且有遮罩特征的大面积浮层
  var nodes = document.body ? document.body.querySelectorAll('div,section,aside,article') : [];
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    if (!el.parentNode) continue;
    var cs;
    try { cs = window.getComputedStyle(el); } catch(e){ continue; }
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (cs.position !== 'fixed') continue;
    var z = parseInt(cs.zIndex || '0', 10) || 0;
    if (z < 100) continue;
    var r = el.getBoundingClientRect();
    if (r.width < vw * 0.3 || r.height < vh * 0.2) continue;
    if (!nameHit(el) && z < 900) continue;
    kill(el);
  }
  // 3. 解除滚动锁定
  try {
    document.documentElement.style.removeProperty('overflow');
    document.body && document.body.style.removeProperty('overflow');
    var cls = ['modal-open','overflow-hidden','no-scroll','noscroll','disabled-scroll','body-lock'];
    for (var i = 0; i < cls.length; i++) {
      document.documentElement.classList.remove(cls[i]);
      document.body && document.body.classList.remove(cls[i]);
    }
  } catch(e){}
  // 4. 同源 iframe 内也清一遍
  try {
    var frames = document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
      try {
        var d = frames[i].contentDocument;
        if (!d) continue;
        var inner = d.querySelectorAll('[role="dialog"],[aria-modal="true"],dialog[open],.modal,.popup,.mask');
        for (var j = 0; j < inner.length; j++) {
          if (inner[j].parentNode) { inner[j].parentNode.removeChild(inner[j]); removed.push('iframe:' + inner[j].tagName); }
        }
      } catch(e){}
    }
  } catch(e){}
  return removed.length;
})()
"""

SCROLL_JS = r"""
(function(){
  window.__sfScrollY = 0;
  window.__sfScrolling = true;
  var h = Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement.scrollHeight);
  var step = Math.max(300, Math.floor(window.innerHeight * 0.85));
  var y = 0;
  window.__sfTimer = setInterval(function(){
    y += step;
    window.scrollTo(0, y);
    if (y >= h) {
      clearInterval(window.__sfTimer);
      window.scrollTo(0, 0);
      window.__sfScrolling = false;
    }
  }, 180);
  return h;
})()
"""


def clean_name(name, limit=70):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" ._")
    if not name:
        name = "网页"
    return name[:limit]


# ------------------------------------------------------------------ 自定义页面
class SaverPage(QWebEnginePage):
    """自动应答 JS 对话框、阻止 window.open 新窗口"""

    def __init__(self, profile, parent=None, logger=None):
        super().__init__(profile, parent)
        self.logger = logger or (lambda m: None)

    def javaScriptAlert(self, origin, msg):
        self.logger("已关闭网页提示框：%s" % (msg or "")[:60])

    def javaScriptConfirm(self, origin, msg):
        self.logger("已自动确认网页对话框：%s" % (msg or "")[:60])
        return True

    def javaScriptPrompt(self, origin, msg, default_value):
        self.logger("已自动关闭网页输入框：%s" % (msg or "")[:60])
        return True, default_value or ""

    def createWindow(self, window_type):
        self.logger("已拦截网页弹出的新窗口")
        return None

    def certificateError(self, error):
        try:
            error.acceptCertificate()
            return True
        except Exception:
            return False

    def javaScriptConsoleMessage(self, level, message, line, source):
        pass


# ------------------------------------------------------------------ 主窗口
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("%s v%s" % (APP_NAME, APP_VER))
        self.resize(1400, 880)
        self.saving = False
        self.cur_url = ""
        self._nav_requested = False

        self.profile = QWebEngineProfile("SfOfflineSaver", self)
        self.profile.setPersistentStoragePath(
            os.path.join(os.environ.get("LOCALAPPDATA", HERE), "SfOfflineSaver", "browser"))
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self._install_singlefile()

        self.page = SaverPage(self.profile, self, self.log)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)

        self._build_ui()

        self.view.setPage(self.page)
        self.page.loadFinished.connect(self.on_load_finished)
        self.page.loadStarted.connect(lambda: self.lbl_status.setText("正在加载…"))

        QTimer.singleShot(0, self.goto_home)

    # ---------------- singlefile 注入
    def _install_singlefile(self):
        d = lib_dir()
        self.sf_ready = False
        if not d:
            return
        try:
            src = io.open(os.path.join(d, "single-file.js"), encoding="utf-8").read()
        except Exception as e:
            self.log("读取 single-file.js 失败：%r" % (e,))
            return
        script = QWebEngineScript()
        script.setName("singlefile")
        script.setSourceCode(src)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        self.profile.scripts().insert(script)
        self.sf_ready = True

    # ---------------- 界面
    def _build_ui(self):
        left = QWidget()
        left.setFixedWidth(360)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 8, 12)
        lv.setSpacing(9)

        title = QLabel("离线网页保存器")
        title.setStyleSheet("font-size:16px;font-weight:600;")
        lv.addWidget(title)

        lv.addWidget(QLabel("网址"))
        url_row = QHBoxLayout()
        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("https://example.com")
        self.ed_url.returnPressed.connect(self.open_url)
        url_row.addWidget(self.ed_url, 1)
        self.btn_open = QPushButton("打开")
        self.btn_open.setFixedWidth(62)
        self.btn_open.clicked.connect(self.open_url)
        url_row.addWidget(self.btn_open)
        lv.addLayout(url_row)

        lv.addWidget(QLabel("保存到"))
        dir_row = QHBoxLayout()
        self.ed_dir = QLineEdit(self.default_dir())
        dir_row.addWidget(self.ed_dir, 1)
        btn_dir = QPushButton("…")
        btn_dir.setFixedWidth(34)
        btn_dir.clicked.connect(self.pick_dir)
        dir_row.addWidget(btn_dir)
        lv.addLayout(dir_row)

        self.btn_local = QPushButton("预览已保存的网页文件…")
        self.btn_local.setMinimumHeight(30)
        self.btn_local.clicked.connect(self.open_local)
        lv.addWidget(self.btn_local)

        wait_row = QHBoxLayout()
        wait_row.addWidget(QLabel("保存前等待"))
        self.sp_wait = QSpinBox()
        self.sp_wait.setRange(0, 120)
        self.sp_wait.setValue(3)
        self.sp_wait.setSuffix(" 秒")
        wait_row.addWidget(self.sp_wait)
        wait_row.addStretch(1)
        lv.addLayout(wait_row)

        box = QGroupBox("保存选项")
        bl = QVBoxLayout(box)
        bl.setSpacing(4)
        self.cb_popup = QCheckBox("保存前自动关闭网页弹窗")
        self.cb_popup.setChecked(True)
        self.cb_scroll = QCheckBox("先滚动页面触发懒加载图片")
        self.cb_scroll.setChecked(True)
        self.cb_hidden = QCheckBox("移除隐藏元素")
        self.cb_hidden.setChecked(True)
        self.cb_styles = QCheckBox("移除未使用的样式与字体")
        self.cb_styles.setChecked(True)
        self.cb_frames = QCheckBox("保留框架/内嵌页面")
        self.cb_frames.setChecked(True)
        self.cb_open_after = QCheckBox("保存后自动打开文件")
        self.cb_open_after.setChecked(False)
        for w in (self.cb_popup, self.cb_scroll, self.cb_hidden, self.cb_styles,
                  self.cb_frames, self.cb_open_after):
            bl.addWidget(w)
        lv.addWidget(box)

        self.btn_save = QPushButton("保存当前网页")
        self.btn_save.setMinimumHeight(40)
        self.btn_save.setStyleSheet(
            "QPushButton{font-size:14px;font-weight:600;background:#2f6fed;color:#fff;"
            "border:none;border-radius:6px;}QPushButton:hover{background:#3b7cf5;}"
            "QPushButton:disabled{background:#8aa8e0;}")
        self.btn_save.clicked.connect(self.save_current)
        lv.addWidget(self.btn_save)

        lv.addWidget(QLabel("运行日志"))
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("font-family:Consolas,monospace;font-size:12px;")
        lv.addWidget(self.txt_log, 1)

        # 右侧浏览器
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 8, 8, 8)
        rv.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        for text, tip, slot in (("←", "后退", lambda: self.view.back()),
                                ("→", "前进", lambda: self.view.forward()),
                                ("⟳", "刷新", lambda: self.view.reload())):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setFixedSize(30, 26)
            b.clicked.connect(slot)
            bar.addWidget(b)
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color:#666;")
        bar.addWidget(self.lbl_status, 1)
        rv.addLayout(bar)

        self.view = QWebEngineView()
        rv.addWidget(self.view, 1)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 1040])
        self.setCentralWidget(split)

        self.progress = QProgressBar()
        self.progress.setMaximumHeight(4)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

        QShortcut(QKeySequence("F5"), self, activated=self.view.reload)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_current)

    # ---------------- 工具
    def default_dir(self):
        d = os.path.join(os.path.expanduser("~"), "Desktop", "离线网页")
        return d if os.path.isdir(d) else os.path.expanduser("~")

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.txt_log.append("[%s] %s" % (ts, msg))

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self.ed_dir.text() or self.default_dir())
        if d:
            self.ed_dir.setText(d)

    def open_local(self):
        start = self.ed_dir.text().strip() or self.default_dir()
        f, _ = QFileDialog.getOpenFileName(
            self, "选择要预览的网页文件", start, "网页文件 (*.html *.htm);;所有文件 (*.*)")
        if not f:
            return
        self._nav_requested = True
        self.ed_url.setText(QUrl.fromLocalFile(f).toString())
        self.lbl_status.setText("正在打开本地文件…")
        self.page.load(QUrl.fromLocalFile(f))
        self.log("预览本地文件：%s" % f)

    def goto_home(self):
        if self._nav_requested:
            return
        html = ("<body style='margin:0;height:100vh;display:flex;align-items:center;"
                "justify-content:center;background:#f7f8fa;color:#9aa0a6;"
                "font:15px \"Microsoft YaHei UI\"'>在左侧输入网址，点击“打开”后在此浏览网页</body>")
        self.page.setHtml(html, QUrl("about:blank"))

    def js(self, code, timeout=30000):
        """同步执行 JS（嵌套事件循环，保证界面不假死）"""
        loop = QEventLoop()
        box = {}

        def cb(res):
            box["v"] = res
            loop.quit()

        self.page.runJavaScript(code, 0, cb)
        QTimer.singleShot(timeout, loop.quit)
        loop.exec()
        return box.get("v")

    def normalize_url(self, text):
        text = (text or "").strip()
        if not text:
            return ""
        if re.match(r"^[a-zA-Z]+://", text) or text.startswith("about:") or text.startswith("file:"):
            return text
        if re.match(r"^[\w.-]+\.[a-zA-Z]{2,}([/:?#].*)?$", text):
            return "https://" + text
        if os.path.exists(text):
            return QUrl.fromLocalFile(os.path.abspath(text)).toString()
        return "https://" + text

    # ---------------- 打开网页
    def open_url(self):
        self._nav_requested = True
        url = self.normalize_url(self.ed_url.text())
        if not url:
            self.log("请先输入网址")
            return
        self.ed_url.setText(url)
        self.cur_url = url
        self.lbl_status.setText("正在加载…")
        self.progress.show()
        self.progress.setRange(0, 0)
        self.page.load(QUrl(url))
        self.log("打开：%s" % url)

    def on_load_finished(self, ok):
        self.progress.hide()
        self.progress.setRange(0, 1)
        if ok:
            self.lbl_status.setText("加载完成：%s" % (self.page.title() or ""))
            self.log("加载完成：%s" % (self.page.title() or self.page.url().toString()))
        else:
            self.lbl_status.setText("加载失败")
            self.log("加载失败，请检查网址是否正确或网络是否可用")

    # ---------------- 保存
    def save_current(self):
        if self.saving:
            return
        if not self.sf_ready:
            QMessageBox.warning(self, APP_NAME, "缺少 single-file.js 内核文件，无法保存。\n请确认程序目录下存在 sflib\\single-file.js。")
            return
        url = self.page.url().toString()
        if not url or url.startswith("about:"):
            self.log("当前没有可保存的网页，请先打开一个网址")
            return
        out_dir = self.ed_dir.text().strip() or self.default_dir()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, "保存目录不可用：%r" % (e,))
            return

        self.saving = True
        self.btn_save.setEnabled(False)
        self.btn_save.setText("正在保存…")
        try:
            self._do_save(url, out_dir)
        except Exception:
            self.log("保存出错：\n" + traceback.format_exc())
        finally:
            self.saving = False
            self.btn_save.setEnabled(True)
            self.btn_save.setText("保存当前网页")

    def _close_popups(self, tag):
        n = self.js(CLEAN_JS, 15000)
        try:
            n = int(float(n))
        except Exception:
            n = 0
        self.log("%s：已关闭 %d 个弹窗/遮罩" % (tag, n))

    def _do_save(self, url, out_dir):
        # 1. 等待页面稳定（弹窗、懒加载元素都会在这段时间出现）
        wait = self.sp_wait.value()
        if wait > 0:
            self.log("等待 %d 秒让页面稳定…" % wait)
            t0 = __import__("time").time()
            while __import__("time").time() - t0 < wait:
                QApplication.processEvents()
                __import__("time").sleep(0.1)

        # 2. 关闭弹窗
        if self.cb_popup.isChecked():
            self._close_popups("清理弹窗")

        # 3. 触发懒加载
        if self.cb_scroll.isChecked():
            self.log("正在滚动页面以触发懒加载…")
            self.js(SCROLL_JS, 15000)
            t0 = __import__("time").time()
            while __import__("time").time() - t0 < 20:
                if not self.js("window.__sfScrolling === true", 5000):
                    break
                QApplication.processEvents()
                __import__("time").sleep(0.25)
            self.log("滚动完成")
            # 滚动后可能又弹出新的浮层，再清一次
            if self.cb_popup.isChecked():
                self._close_popups("滚动后二次清理")

        # 4. 调用 SingleFile
        opts = {
            "removeHiddenElements": bool(self.cb_hidden.isChecked()),
            "removeUnusedStyles": bool(self.cb_styles.isChecked()),
            "removeUnusedFonts": bool(self.cb_styles.isChecked()),
            "removeFrames": not self.cb_frames.isChecked(),
            "blockScripts": False,
            "compressHTML": False,
            "loadDeferredImages": True,
            "loadDeferredImagesMaxIdleTime": 1200,
            "insertSingleFileComment": True,
            "saveFavicon": True,
            "displayStats": False,
        }
        self.log("开始生成离线单文件…")
        js = (
            "(async()=>{try{"
            "window.__sfres=null;window.__sferr=null;window.__sflen=-1;window.__sfdone=false;"
            "const r=await singlefile.getPageData(%s, {}, document, window);"
            "window.__sfres=(r&&r.content)||'';window.__sflen=window.__sfres.length;"
            "window.__sfdone=true;"
            "}catch(e){window.__sferr=String(e&&e.stack||e);window.__sfdone=true;}})();1"
        ) % json.dumps(opts, ensure_ascii=False)
        self.page.runJavaScript(js, 0)

        t0 = __import__("time").time()
        ln = -1
        while __import__("time").time() - t0 < 180:
            v = self.js("window.__sfdone ? (window.__sferr ? -1 : window.__sflen) : -2", 5000)
            try:
                v = int(float(v))
            except Exception:
                v = -2
            if v == -1:
                err = self.js("window.__sferr||''", 5000)
                self.log("生成失败：%s" % str(err)[:400])
                return
            if v > 0:
                ln = v
                break
            QApplication.processEvents()
            __import__("time").sleep(0.3)

        if ln <= 0:
            self.log("生成超时，页面可能过大或脚本被拦截")
            return

        # 5. 分块取回
        self.log("正在取回内容（%.1f KB）…" % (ln / 1024.0))
        parts = []
        idx = 0
        step = 200000
        while idx < ln:
            chunk = self.js("window.__sfres.substr(%d,%d)" % (idx, step), 120000)
            if not chunk:
                break
            parts.append(chunk)
            idx += len(chunk)
            QApplication.processEvents()
        html = "".join(parts)
        if len(html) != ln:
            self.log("注意：内容长度不一致（%d/%d），可能被截断" % (len(html), ln))

        title = self.page.title() or "网页"
        fname = "%s_%s.html" % (clean_name(title), datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        out = os.path.join(out_dir, fname)
        try:
            with io.open(out, "w", encoding="utf-8") as fp:
                fp.write(html)
        except Exception as e:
            self.log("写入文件失败：%r" % (e,))
            return

        self.log("保存成功：%s（%.2f MB）" % (out, os.path.getsize(out) / 1048576.0))
        self.lbl_status.setText("已保存：%s" % fname)
        QApplication.beep()
        try:
            if self.cb_open_after.isChecked():
                QDesktopServices.openUrl(QUrl.fromLocalFile(out))
        except Exception:
            pass


SELFTEST_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>自检页面</title><style>body{font-family:sans-serif;padding:40px}
.mask{position:fixed;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:9999}
.dlg{position:fixed;left:50%;top:40%;transform:translate(-50%,-50%);width:400px;background:#fff;
padding:24px;border-radius:10px;z-index:10000}</style></head><body>
<h1>自检正文</h1><p>这一段应当被保存下来。</p>
<div class="mask"></div>
<div class="dlg" role="dialog" aria-modal="true"><h3>弹窗标题</h3><button>按钮</button></div>
<script>document.body.classList.add('modal-open');</script>
</body></html>"""


def run_selftest(app):
    out = os.path.join(os.environ.get("TEMP", HERE), "sf_selftest")
    try:
        os.makedirs(out, exist_ok=True)
    except Exception:
        pass
    src = os.path.join(out, "selftest_src.html")
    io.open(src, "w", encoding="utf-8").write(SELFTEST_HTML)
    w = MainWindow()
    w.resize(1400, 880)
    w.ed_dir.setText(out)
    w.sp_wait.setValue(1)
    w.show()
    w._nav_requested = True
    QTimer.singleShot(600, lambda: w.page.load(QUrl.fromLocalFile(src)))

    def after():
        try:
            w.grab().save(os.path.join(out, "shot.png"))
        except Exception:
            pass
        w.save_current()
        io.open(os.path.join(out, "result.txt"), "w", encoding="utf-8").write(w.txt_log.toPlainText())
        app.quit()

    QTimer.singleShot(4500, after)


def main():
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu-shader-disk-cache")
    app = QApplication(sys.argv)
    app.setApplicationName("SfOfflineSaver")
    app.setOrganizationName("Marvis")
    icon = res_path("app.ico")
    if os.path.isfile(icon):
        app.setWindowIcon(QIcon(icon))
    if "--selftest" in sys.argv:
        run_selftest(app)
        app.exec()
        return
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
