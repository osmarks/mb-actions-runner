import random
import time
import requests
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session
import paramiko
import os, os.path
import base64

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

def do_req(method, url, auth, json=None, propagate_http_error=True):
    headers, auth_arg = ({"Authorization": auth}, None) if isinstance(auth, str) else (None, auth)
    res = requests.request(method, url, headers=headers, json=json, auth=auth_arg)
    if propagate_http_error and not (200 <= res.status_code <= 299): raise Exception(f"{method} {url} failed: {res.json().get('error', res.text)} (HTTP {res.status_code})")
    return res

def acquire_mythic_token(current=None):
    if isinstance(current, dict) and "access_token" in current and current["expires_at"] < (time.time() - 5): return current
    id, secret = mb_auth
    client = BackendApplicationClient(client_id=id)
    oauth = OAuth2Session(client=client)
    return oauth.fetch_token(client_secret=secret, token_url="https://auth.mythic-beasts.com/login", client_id=id)

def gc_old_servers(token):
    # Go through autostarted servers and shut down ones where time string indicates they're more than 12 hours old.
    for server_id in do_req("GET", f"{mb_api}/beta/vps/servers", f"Bearer {token['access_token']}").json():
        split = server_id.split("cirunner", 1)
        if len(split) == 2:
            ts = int(split[-1][:10], 16)
            if ts < (time.time() - (60*60*12)):
                print("Shutting down", server_id)
                stop_server(token, server_id)

def start_server(server_id):
    token = acquire_mythic_token()
    gc_old_servers(token)
    if not server_id:
        server_id = f"gha{int(time.time()):09x}{random.randint(0, 0xFFFF_FFFF):08x}"
    key = paramiko.ECDSAKey.generate()
    result = do_req("POST", f"{mb_api}/beta/vps/servers/{server_id}",
        f"Bearer {token['access_token']}",
        {
           "product": vdstype,
           "ssh_keys": f"ecdsa-sha2-nistp256 {key.get_base64()}",
           "disk_size": disk_size,
           "image": image_name
        }
    )
    # Poll for server boot/install status
    while True:
        poll_result = do_req("GET", result.headers["Location"], f"Bearer {token['access_token']}").json()
        if poll_result["status"] == "running":
            return key, server_id, poll_result
        else:
            print(poll_result["status"])
            token = acquire_mythic_token(token)
            time.sleep(10)

def get_runner_by_name(gh_auth, name):
    runners = do_req("GET", f"{gh_api}/repos/{owner}/{repo}/actions/runners", gh_auth).json()
    for runner in runners["runners"]:
        if runner["name"] == name: return runner["id"]

def configure_server(ip, port, key, regtoken, id):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
    client.connect(ip, port, "root", pkey=key)
    print("Configuring runner")
    # Download and start up self-hosted runner program
    commands = [
        "wget https://github.com/actions/runner/releases/download/v2.279.0/actions-runner-linux-x64-2.279.0.tar.gz",
        "tar xzf ./actions-runner-linux-x64-2.279.0.tar.gz",
        f"env RUNNER_ALLOW_RUNASROOT=1 ./config.sh --url https://github.com/{owner}/{repo} --token {regtoken} --labels {id} --unattended",
        "bash -c 'env RUNNER_ALLOW_RUNASROOT=1 nohup ./run.sh > /dev/null 2> /dev/null < /dev/null &'",
        """bash -c 'echo "@reboot root cd /root/ && env RUNNER_ALLOW_RUNASROOT=1 nohup ./run.sh > /dev/null 2> /dev/null < /dev/null &" >> /etc/crontab'""",
        "chown root:root /root"
    ]
    if "INPUT_SSH-PUBKEY" in os.environ:
        commands.append(f"bash -c 'echo {os.environ['INPUT_SSH-PUBKEY']} >> /root/.ssh/authorized_keys'")
    print(commands)
    for command in commands:
        _, stdout, stderr = client.exec_command(command)
        print(stdout.readlines(), stderr.readlines())
    print("Startup done")
    client.close()

def stop_server(server_id):
    # delete server and runner
    token = acquire_mythic_token()
    gc_old_servers(token)
    do_req("DELETE", f"{mb_api}/beta/vps/servers/{server_id}", f"Bearer {token['access_token']}")
    rid = get_runner_by_name(gh_auth, server_id)
    do_req("DELETE", f"{gh_api}/repos/{owner}/{repo}/actions/runners/{rid}", gh_auth)

def unsuspend_server(server_id):
    token = acquire_mythic_token()
    # obtain current status of server to see if it exists or not
    current_status = do_req("GET", f"{mb_api}/beta/vps/servers/{server_id}", f"Bearer {token['access_token']}", propagate_http_error=False)
    if current_status.status_code == 404 or current_status.json().get("error") == "Server does not exist or access denied":
        if os.environ.get("INPUT_UNSUSPEND-ONLY") == "true":
            raise Exception("Server does not exist and not creating it")
        print("Creating server as it does not exist")
        return start_and_configure(server_id)
    print(current_status.json())
    # if it is down, wake it up and poll until up
    do_req("PUT", f"{mb_api}/beta/vps/servers/{server_id}/dormant", f"Bearer {token['access_token']}", { "dormant": False, "product": vdstype })
    do_req("PUT", f"{mb_api}/beta/vps/servers/{server_id}/power", f"Bearer {token['access_token']}", { "power": "power-on" })
    while True:
        poll_result = do_req("GET", f"{mb_api}/beta/vps/servers/{server_id}", f"Bearer {token['access_token']}").json()
        if poll_result["status"] == "running":
            return server_id, poll_result
        else:
            print(poll_result["status"])
            token = acquire_mythic_token(token)
            time.sleep(5)

def start_and_configure(server_id):
    # generate registration token to initialize a new self-hosted runner
    runner_token = do_req("POST", f"{gh_api}/repos/{owner}/{repo}/actions/runners/registration-token", auth=gh_auth).json()["token"]
    key, id, info = start_server(server_id)
    print(f"::set-output name=server-id::{id}")
    proxy = info["ssh_proxy"]
    # add delay for admin proxy URL to work
    time.sleep(10)
    # SSH proxy is needed as the VMs don't seem to have IPv6 capability
    key.write_private_key_file("key.tmp")
    configure_server(proxy["hostname"], proxy["port"], key, runner_token, id)

def suspend_server(server_id):
    token = acquire_mythic_token()
    # servers must be powered down before dormancy
    do_req("PUT", f"{mb_api}/beta/vps/servers/{server_id}/power", f"Bearer {token['access_token']}", { "power": "shutdown" })
    # try for clean shutdown and power off after some time
    time.sleep(10)
    do_req("PUT", f"{mb_api}/beta/vps/servers/{server_id}/power", f"Bearer {token['access_token']}", { "power": "power-off" })
    do_req("PUT", f"{mb_api}/beta/vps/servers/{server_id}/dormant", f"Bearer {token['access_token']}", { "dormant": True })

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