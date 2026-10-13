import webview
import time
import threading

webview.settings['WEBVIEW2_RUNTIME_PATH'] = r'C:\Windows\System32\Microsoft-Edge-WebView'

w = webview.create_window(
    'Claude Master Test',
    html='<html><body style="background:#1e1e1e;color:white;"><h1>Claude Master WebView2 Shell</h1><p>Running native on Windows</p></body></html>',
    width=600,
    height=400
)

def timer():
    time.sleep(2)
    print('Destroying window after 2s...')
    w.destroy()

threading.Thread(target=timer, daemon=True).start()
webview.start()
print('Finished cleanly.')
