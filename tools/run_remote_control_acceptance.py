import json
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.control_center.server import ControlCenterServer, load_or_create_token
from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore


class JarvisStub:
    last_mission = None


class RuntimeStub:
    BOOTING = "BOOTING"
    STOPPED = "STOPPED"
    def __init__(self):
        self.state = "SLEEPING"
        self.jarvis = JarvisStub()
        self.completed_tasks = 0
        self.last_error = self.last_mission_status = None
        self.stop_requested = False
        self.received = []
    def execute(self, goal):
        self.received.append(goal)
        self.completed_tasks += 1
        return "accepted through normal runtime pipeline"
    def shutdown(self):
        self.state = self.STOPPED


def start(store, runtime, token, port):
    service = ControlCenterService(runtime, store)
    server = ControlCenterServer(("127.0.0.1", port), service, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return service, server, thread


if __name__ == "__main__":
    root = Path("workspace/remote_acceptance")
    store = ControlCenterStore(root / "state.json")
    token = load_or_create_token(root / "session.token")
    runtime1 = RuntimeStub()
    service1, server1, thread1 = start(store, runtime1, token, 0)
    port = server1.server_port
    approval = service1.create_approval("finance_real_trade", {"need": "future BTC approval",
        "why": "mobile acceptance", "risk": "HIGH", "cost": 10,
        "expected_result": "audit record only"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        response = page.goto(f"http://127.0.0.1:{port}/?token={token}")
        if response is None or response.status != 200:
            raise RuntimeError(f"bootstrap failed: {response.status if response else 'no response'} {page.url} {page.content()[:300]}")
        page.wait_for_selector("#backendKpi")
        page.click('[data-view="approvals"]')
        page.fill(f"#reason-{approval['id']}", "Rejected safely from 390x844 phone UI")
        reject = page.locator(f".reject[onclick*='{approval['id']}']")
        button_height = reject.bounding_box()["height"]
        approval_response = page.evaluate("""async ({id}) => {
          const r=await fetch(`/api/approvals/${id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({reason:'Rejected safely from 390x844 phone UI'})});
          return {status:r.status,body:await r.json()}; }""", {"id": approval["id"]})
        if approval_response["status"] != 200:
            raise RuntimeError(f"approval API failed: {approval_response}")
        for _ in range(100):
            current = next(item for item in service1.store.snapshot()["approvals"] if item["id"] == approval["id"])
            if current["status"] == "REJECTED": break
            time.sleep(.02)
        else: raise RuntimeError("phone approval decision was not persisted")
        voice_result = page.evaluate("""async () => {
          const r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({goal:'Jarvis, durum.',source:'voice'})}); return await r.json(); }""")
        for _ in range(100):
            if not service1.busy: break
            time.sleep(.01)
        layout = page.evaluate("({body:document.body.scrollWidth,viewport:window.innerWidth,backend:document.querySelector('#backendKpi').textContent})")
        server1.shutdown(); server1.server_close(); thread1.join(2)

        runtime2 = RuntimeStub()
        service2, server2, thread2 = start(ControlCenterStore(root / "state.json"), runtime2, token, port)
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("#backendKpi")
        restart_access = page.locator("#backendKpi").inner_text()
        persisted = service2.store.snapshot()
        health = service2.health()
        server2.shutdown(); server2.server_close(); thread2.join(2)
        browser.close()

    decision = next(item for item in persisted["approvals"] if item["id"] == approval["id"])
    print(json.dumps({"stable_url": f"http://127.0.0.1:{port}/", "restart_access": restart_access,
        "session_token_reused": token == load_or_create_token(root / "session.token"),
        "phone_viewport": layout, "minimum_reject_button_height": button_height,
        "approval": {"status": decision["status"], "reason": decision["decision_reason"],
                     "decided_at": decision["decided_at"]},
        "voice_source": persisted["missions"][-1]["source"], "voice_goal": persisted["missions"][-1]["goal"],
        "health": health, "public_binding": False, "live_trade_executed": False,
        "voice_submission": voice_result["status"]}, ensure_ascii=False, indent=2))
