# Mythic Beasts GitHub Actions Runner

Run your GitHub Actions workflows on Mythic Beasts [on-demand VPSes](https://www.mythic-beasts.com/blog/2021/05/14/vps-api-on-demand-billing-and-dormant-vpss/) automatically.
This is useful if you want to run tasks with more computing power than provided by GitHub runners, save money with a lower-end VPS (GitHub [will only bill you](https://docs.github.com/en/free-pro-team@latest/actions/hosting-your-own-runners/about-self-hosted-runners) for the time spent starting/stopping the VPS), or (using suspend/unsuspend mode) keep data around between runs without the cost of running something constantly.

Starting up an on-demand VPS takes about 4 minutes from action start to runner activation, so it is suitable for longer workloads. Unsuspending and booting one is substantially faster (about 1 minute), so it is better for shorter tasks.

## Setup

You'll need a [personal access token](https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token) with scope "repo". This should be stored in a secret in the repository (`GH_TOKEN`).

Also create a [Mythic Beasts API token](https://mythic-beasts.com/customer/api-users) with virtual server provisioning access. The client ID and client secret should also be stored in repository secrets (`MB_TOKEN` and `MB_SECRET`).

Copy either `example-suspend.yml` (if you want to suspend and unsuspend a VPS) or `example-start-stop.yml` (if you want to start and stop a new clean VPS each time) into `.github/workflows` and edit it as appropriate to run whatever actions you want - you should only need to change the `server-id` to any unique alphanumeric <20-character server name string for `example-suspend.yml` and nothing for start-stop.

Configuration options:

* `server-id` if you use the suspend/unsuspend mode - this is directly given to the VPS API, so it must be globally unique, 20 characters or less, and alphanumeric
* `unuspend-only` for suspend/unsuspend mode: will not not create a new VPS if the named one doesn't exist, if this is set to `true`.
* `vps-type` (https://www.mythic-beasts.com/support/api/vps#ep-get-vpsproducts): configure VPS specifications. Defaults to VPSX16 (2 cores, 4GB RAM).
* `vps-disk` (https://www.mythic-beasts.com/support/api/vps#ep-get-vpsdisk-sizes): configure VPS disk space. Defaults to 5120 (5GB).
* `image-id` (https://www.mythic-beasts.com/support/api/vps#ep-get-vpsimages): set the image to load the VPS with initially. Defaults to Debian Buster. Make sure cloud-init is supported as this used to install.
* `ssh-pubkey` is an SSH public key to add to all created VPSes for management/debugging purposes.
* `gh-token-owner` is needed if the personal access token's owner isn't the same as the repository's owner