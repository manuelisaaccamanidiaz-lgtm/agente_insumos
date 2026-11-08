"""python -m servidor → arranca Abona en http://127.0.0.1:8000 y abre el navegador."""
import threading
import webbrowser

import uvicorn

URL = "http://127.0.0.1:8000"

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    uvicorn.run("servidor.api:app", host="127.0.0.1", port=8000)
