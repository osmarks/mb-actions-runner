import random
import time
import requests
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session
import os, os.path
import json.decoder

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f.readlines():
            start, end = line.split("=", 1)
            end = end.strip()
            os.environ[start] = end

owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
vdstype = os.environ["INPUT_VPS-TYPE"]
mb_auth = (os.environ["INPUT_MB-TOKEN"], os.environ["INPUT_MB-SECRET"])
gh_auth = (owner, os.environ["INPUT_GH-TOKEN"])
image_name = os.environ["INPUT_IMAGE-ID"]
gh_api = "https://api.github.com"
mb_api = "https://api.mythic-beasts.com"
disk_size = int(os.environ["INPUT_VPS-DISK"])

def do_req(method, url, auth, jsondata=None, propagate_http_error=True):
    headers, auth_arg = ({"Authorization": auth}, None) if isinstance(auth, str) else (None, auth)
    res = requests.request(method, url, headers=headers, json=jsondata, auth=auth_arg)
    if propagate_http_error and not (200 <= res.status_code <= 299):
        try:
            errtext = res.json()["error"]
        except (json.decoder.JSONDecodeError, KeyError):
            errtext = res.text
        raise Exception(f"{method} {url} failed: {errtext} (HTTP {res.status_code})")
    return res

def do_github_req(method, url, *args, **kwargs): return do_req(method, gh_api + url, gh_auth, *args, **kwargs)

current_mb_token = None
def do_mb_req(method, url, *args, **kwargs):
    global current_mb_token
    current_mb_token = acquire_mythic_token(current_mb_token)
    if not url.startswith(mb_api): url = mb_api + url
    return do_req(method, url, "Bearer " + current_mb_token["access_token"], *args, **kwargs)

def acquire_mythic_token(current=None):
    if isinstance(current, dict) and "access_token" in current and current["expires_at"] > (time.time() + 5): return current
    id, secret = mb_auth
    client = BackendApplicationClient(client_id=id)
    oauth = OAuth2Session(client=client)
    return oauth.fetch_token(client_secret=secret, token_url="https://auth.mythic-beasts.com/login", client_id=id)

def gc_old_servers():
    # Go through autostarted servers and shut down ones where time string indicates they're more than 12 hours old.
    for server_id in do_mb_req("GET", "/beta/vps/servers").json():
        split = server_id.split("cirunner", 1)
        if len(split) == 2:
            ts = int(split[-1][:10], 16)
            if ts < (time.time() - (60*60*12)):
                print("Shutting down", server_id)
                stop_server(server_id)

def start_server(server_id, regtoken):
    gc_old_servers()
    if not server_id:
        server_id = f"gha{int(time.time()):09x}{random.randint(0, 0xFFFF_FFFF):08x}"
    commands = [
        "mkdir /root/runner",
        "cd /root/runner",
        "echo Downloading",
        "wget -q https://github.com/actions/runner/releases/download/v2.279.0/actions-runner-linux-x64-2.279.0.tar.gz",
        "tar xzf ./actions-runner-linux-x64-2.279.0.tar.gz",
        "echo Extracted",
        f"env RUNNER_ALLOW_RUNASROOT=1 ./config.sh --url https://github.com/{owner}/{repo} --token {regtoken} --labels {server_id} --unattended",
        "env RUNNER_ALLOW_RUNASROOT=1 nohup ./run.sh > /dev/null 2> /dev/null < /dev/null &",
        "echo Configured and started",
        """echo "@reboot root cd /root/runner/ && env RUNNER_ALLOW_RUNASROOT=1 nohup ./run.sh > /dev/null 2> /dev/null < /dev/null &" >> /etc/crontab""",
    ]
    result = do_mb_req("POST", f"/beta/vps/servers/{server_id}",
        {
           "product": vdstype,
           "ssh_keys": os.environ.get("INPUT_SSH-PUBKEY", ""),
           "disk_size": disk_size,
           "image": image_name,
           "user_data_string": "#!/bin/sh\n" + "\n".join(commands)
        }
    )
    # Poll for server boot/install status
    while True:
        poll_result = do_mb_req("GET", result.headers["Location"]).json()
        if poll_result["status"] == "running":
            return server_id, poll_result
        else:
            print(poll_result["status"])
            time.sleep(10)

def get_runner_by_name(name):
    runners = do_github_req("GET", f"/repos/{owner}/{repo}/actions/runners").json()
    for runner in runners["runners"]:
        if runner["name"] == name: return runner["id"]

def stop_server(server_id):
    # delete server and runner
    gc_old_servers()
    do_mb_req("DELETE", f"/beta/vps/servers/{server_id}")
    rid = get_runner_by_name(server_id)
    do_github_req("DELETE", f"/repos/{owner}/{repo}/actions/runners/{rid}")

def unsuspend_server(server_id):
    # obtain current status of server to see if it exists or not
    current_status = do_mb_req("GET", f"/beta/vps/servers/{server_id}", propagate_http_error=False)
    if current_status.status_code == 404 or current_status.json().get("error") == "Server does not exist or access denied":
        if os.environ.get("INPUT_UNSUSPEND-ONLY") == "true":
            raise Exception("Server does not exist and not creating it")
        print("Creating server as it does not exist")
        return start_and_configure(server_id)
    print(current_status.json())
    # if it is down, wake it up and poll until up
    do_mb_req("PUT", f"/beta/vps/servers/{server_id}/dormant", { "dormant": False, "product": vdstype })
    do_mb_req("PUT", f"/beta/vps/servers/{server_id}/power", { "power": "power-on" })
    while True:
        poll_result = do_mb_req("GET", f"/beta/vps/servers/{server_id}").json()
        if poll_result["status"] == "running":
            return server_id, poll_result
        else:
            print(poll_result["status"])
            time.sleep(5)

def start_and_configure(server_id):
    # generate registration token to initialize a new self-hosted runner
    runner_token = do_github_req("POST", f"/repos/{owner}/{repo}/actions/runners/registration-token").json()["token"]
    id, info = start_server(server_id, runner_token)
    print(f"::set-output name=server-id::{id}")

def suspend_server(server_id):
    # servers must be powered down before dormancy
    do_mb_req("PUT", f"/beta/vps/servers/{server_id}/power", { "power": "shutdown" })
    # try for clean shutdown and power off after some time
    time.sleep(10)
    do_mb_req("PUT", f"/beta/vps/servers/{server_id}/power", { "power": "power-off" })
    do_mb_req("PUT", f"/beta/vps/servers/{server_id}/dormant", { "dormant": True })

action = os.environ["INPUT_ACTION"]
if action == "start":
    start_and_configure(os.environ.get("INPUT_SERVER-ID", None))
elif action == "stop":
    stop_server(os.environ["INPUT_SERVER-ID"])
elif action == "suspend":
    suspend_server(os.environ["INPUT_SERVER-ID"])
elif action == "unsuspend":
    unsuspend_server(os.environ["INPUT_SERVER-ID"])
else:
    raise ValueError(f"{action} is not a valid action")