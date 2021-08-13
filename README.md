# Mythic Beasts GitHub Actions Runner

Run your GitHub Actions workflows on Mythic Beasts [on-demand VPSes](https://www.mythic-beasts.com/blog/2021/05/14/vps-api-on-demand-billing-and-dormant-vpss/) automatically.
This is useful if you want to run tasks with more computing power than provided by GitHub runners, save money with a lower-end VPS (GitHub [will only bill you](https://docs.github.com/en/free-pro-team@latest/actions/hosting-your-own-runners/about-self-hosted-runners) for the time spent starting/stopping the VPS), or (using suspend/unsuspend mode) keep data around between runs without the cost of running something constantly.

Starting up an on-demand VPS takes about 4 minutes from action start to runner activation, so it is suitable for longer workloads. Unsuspending and booting one is substantially faster (about 1 minute), so it is better for shorter tasks.

## Setup

You'll need a [personal access token](https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token) with scope "repo". This should be stored in a secret in the repository (`GH_SECRET`).

Also create a [Mythic Beasts API token](https://mythic-beasts.com/customer/api-users) with virtual server provisioning access. The client ID and client secret should also be stored in repository secrets (`MB_TOKEN` and `MB_SECRET`).

Copy either `example-suspend.yml` (if you want to suspend and unsuspend a VPS) or `example-start-stop.yml` (if you want to start and stop a new clean VPS each time) into `.github/workflows` and edit it as appropriate to run whatever actions you want - you should only need to change the `server-id` to any unique alphanumeric <20-character server name string for `example-suspend.yml` and nothing for start-stop.

Optionally, configure `ssh-pubkey` to install SSH public keys in the servers or add `unsuspend-only: true` to an `unsuspend` action to prevent a new server from being configured if the specified one does not exist.