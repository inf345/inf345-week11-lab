# INF 345 — Week 11 practice: your service, described as code

**Tuesday 24 November · Group A 12:30 · Group B 13:30 · online, on your own laptop**

**This lab starts the infrastructure half of M6.** M6 is due **Sunday 6 December, 23:59**
(Almaty time, judged by commit time). The checker for this half, `check_iac.py`, is in this
repository. It is the rubric: run it on yourself as often as you like.

**At the end you will have** an `infra/` folder in your project that runs your M3 image with
Terraform — committed with its lock file and without any state — and an `ansible/` playbook
that changes nothing the second time it runs.

Part A (Terraform) is part of M6. Part B (Ansible) is not marked in M6, but it is what most
Kazakh job postings ask for — do it.

---

## Before the lab: do this at home (about 30 minutes)

Tuesday's fifty minutes are for Terraform and Ansible, not for installing things.

**1. Docker is running.** `docker version` shows a `Server:` section (Week 5). No Docker on
your laptop at all? Read [No Docker on your laptop?](#no-docker-on-your-laptop) — you can
still do M6.

**2. Install Terraform** — in the terminal you will use on Tuesday:

| Your system | Install |
|---|---|
| **Windows, recommended: Ubuntu (WSL)** | the three lines for Ubuntu below, inside the Ubuntu terminal |
| Windows without WSL (PowerShell) | `winget install --exact --id Hashicorp.Terraform`, then open a **new** terminal |
| macOS | `brew tap hashicorp/tap` then `brew install hashicorp/tap/terraform` |
| Ubuntu / Debian (and WSL) | the three lines below |

```bash
wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install terraform
```

These are HashiCorp's own commands (developer.hashicorp.com/terraform/install). Then:

```bash
terraform version        # Terraform v1.17.x or v1.16.x - any 1.10 or newer is fine
```

**OpenTofu instead of Terraform is fine.** Everything on this page works with `tofu` in place
of `terraform` (OpenTofu 1.13: `winget install --exact --id=OpenTofu.Tofu`, `brew install
opentofu`, or opentofu.org/docs/intro/install). The checker accepts its lock file too.

**3. Install Ansible — only on Linux, macOS or WSL.** Ansible cannot run on Windows itself
(its own install guide says so). Windows without WSL? Skip this; Part B has two other ways.

```bash
sudo apt update && sudo apt install -y pipx     # Ubuntu / WSL (macOS: brew install pipx)
pipx install ansible-core
pipx ensurepath                                  # then open a NEW terminal
ansible-playbook --version                       # core 2.21.x on Ubuntu 24.04, 2.22.x on newer Python (2.17+ is fine)
```

**4. Know your image.** Your repository page → **Packages** → your package. Copy one tag that
is a **full 40-character commit SHA**. The package must be public (M3). Check it like a
stranger would:

```bash
docker logout ghcr.io
docker pull ghcr.io/<you>/<your-project>:<the SHA>      # lowercase owner and name
```

> **No working M3 image?** Use the course rescue image for this lab — the lecturer's notes
> service, which honours `PORT` and answers `/healthz`:
> `ghcr.io/inf345/notes-rescue:84921690055cf871e6cfd1c57885a754b4172897` (Intel and Apple
> M-series). M6 checks your `infra/` code, not which image it runs, so you lose nothing in
> M6 — and you fix M3 separately.

**5. Python 3.9 or newer, for the checker:** `python3 --version`. It needs no packages.

**6. Get this lab's files**, once, next to your project:

```bash
git clone https://github.com/inf345/inf345-week11-lab.git ~/inf345-week11-lab
```

---

## Part A — Terraform (about 25 minutes)

Work in **your project repository**, on a branch:

```bash
cd ~/path/to/your-project
git switch main && git pull
git switch -c infra
```

### Step 1 — `.gitignore` first. Before anything else.

```bash
cat >> .gitignore <<'EOF'

# Terraform: state holds real IDs and secrets; .terraform/ is a download cache.
# Do NOT add .terraform.lock.hcl here - it must be committed.
*.tfstate
*.tfstate.*
.terraform/
*.tfvars
*.tfplan
crash.log
EOF
git add .gitignore && git commit -m "Ignore Terraform state and cache"
```

**Why first:** M6 scores **0** if a state file or anything from `.terraform/` is in **any
commit** — even one you deleted a minute later. Monday's DEMO 3 showed why: the state file
holds every value in plain text, passwords included.

> **Decide:** why is `.terraform.lock.hcl` *not* on this list? (Step 3 answers it.)

### Step 2 — Copy the scaffold and fill the seven blanks

```bash
cp -r ~/inf345-week11-lab/starter/infra .
```

You now have four files. Each `____` is a blank; the comment above it is the question. Every
blank is a decision from Monday's lecture.

| File | What it holds | Blanks |
|---|---|---|
| `infra/versions.tf` | which provider, which versions | **1** who publishes the Docker provider · **2** a constraint that accepts new 4.x and never 5.0 |
| `infra/variables.tf` | the inputs, each with a description and a default | **3** a one-sentence description · **4** your image's full commit SHA |
| `infra/main.tf` | the image, a network, the container | **5** a reference to the image's ID · **6** the port inside the container · **7** a reference to the network's name |
| `infra/outputs.tf` | values printed after `apply` | none |

Hints, if you are stuck for more than two minutes:
- Blank 1 is the name on the registry, `namespace/name`. Monday's slide 9 shows it.
- Blank 2 uses `~>` with **two** numbers. `~> 4.6` means "4.6 or newer, below 5.0".
- Blank 4: the owner and repository in **lowercase**, then `:`, then the 40 characters.
- Blanks 5 and 7 have the shape `resource_type.resource_name.attribute`. The resources in
  this file are called `app`. The attributes you need are `image_id` and `name`.
- Blank 6: look at the `env` line two lines above it. Inside the container, your app listens
  on whatever `PORT` says.

### Step 3 — `init`

```bash
cd infra
terraform init
```

> **Checkpoint.** `Terraform has been successfully initialized!` — and a new file,
> `.terraform.lock.hcl`. Open it: a `version` (4.7.0 in November 2026) and a list of `hashes`. That is the
> answer to Step 1's question: it records exactly which provider you used and its
> checksums, and Terraform's own message tells you to *include this file in your version
> control repository*. The folder `.terraform/` next to it is only a download cache.

### Step 4 — `fmt` and `validate`

```bash
terraform fmt          # rewrites your files in the standard layout; prints the names it changed
terraform validate
```

> **Checkpoint.** `Success! The configuration is valid.` If not, Common failures below has
> the usual messages, with the line to look at.

### Step 5 — `plan`, and read it

```bash
terraform plan
```

> **Checkpoint.** Three blocks that start with `+`, and at the end:
> `Plan: 3 to add, 0 to change, 0 to destroy.` Find your image name in the
> `docker_image.app` block. Nothing has been created yet: a plan only reads and compares.

`plan` on a new folder does not even need Docker. The next step does.

### Step 6 — `apply`, and call your own service

First, make sure Terraform can find Docker:

| Where you run Terraform | What to do |
|---|---|
| Ubuntu (WSL) with Docker Desktop's WSL integration on | nothing — the provider uses `unix:///var/run/docker.sock` |
| Windows PowerShell with Docker Desktop | nothing — on Windows the provider uses Docker Desktop's named pipe, `npipe:////./pipe/docker_engine` |
| macOS with Docker Desktop | `export DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"` in this terminal (Docker Desktop's socket is in your home folder unless its "default Docker socket" setting is on) |
| Linux | your user is in the `docker` group (`docker ps` works without `sudo`) |

```bash
terraform apply                 # read the plan it shows, then type: yes
docker ps                       # inf345-app is Up
curl "$(terraform output -raw healthz_url)"
```

In PowerShell, the last line is `curl.exe http://localhost:8080/healthz`.

> **Checkpoint.** Your `/healthz` answer. Then:
> ```bash
> ls -a                         # terraform.tfstate is here now
> terraform state list          # docker_container.app, docker_image.app, docker_network.app
> git status                    # terraform.tfstate does NOT appear - Step 1 is working
> ```
> Open `terraform.tfstate` once and find your container's ID in it — the same ID that
> `docker ps` shows.

### Step 7 — Predict, then plan two changes

Predict first, for each: will Terraform **change** the container (`~`) or **replace** it (`-/+`)?

```bash
terraform plan -var restart_policy=unless-stopped
terraform plan -var host_port=9090
```

> **Checkpoint.** The first plan says `~ restart = "no" -> "unless-stopped"` and
> `Plan: 0 to add, 1 to change, 0 to destroy.` The second says
> `~ external = 8080 -> 9090 # forces replacement` and `Plan: 1 to add, 0 to change, 1 to destroy.`
> Docker can change a restart policy on a running container, but not its published ports.

These are only plans: nothing changed. (In a team, a change like this is a one-line edit in a
pull request, with the plan attached.)

### Step 8 — Drift: delete it behind Terraform's back

```bash
docker rm -f inf345-app         # "somebody clicked something"
terraform plan
```

> **Checkpoint.** `Note: Objects have changed outside of Terraform`, then
> `# docker_container.app has been deleted`, then `# docker_container.app will be created`
> and `Plan: 1 to add, 0 to change, 0 to destroy.` Terraform was not watching; `plan`
> asked Docker what really exists before comparing.

```bash
terraform apply -auto-approve
curl "$(terraform output -raw healthz_url)"
```

### Step 9 — Commit, check, push

```bash
cd ..
git add infra/
git status
```

> **Checkpoint.** `git status` lists the four `.tf` files **and `infra/.terraform.lock.hcl`** —
> and nothing called `.tfstate`, nothing under `.terraform/`. If you see a state file here,
> stop: run `git restore --staged <that file>` and fix `.gitignore` first.

```bash
git commit -m "M6: describe my service with Terraform"
python3 ~/inf345-week11-lab/check_iac.py --path . --tool terraform     # or --tool tofu
git push -u origin infra
```

Open a pull request and merge it.

> **Checkpoint.** The checker ends with `RESULT: 25/25`. Every problem it finds is listed at
> once, with the file and line. It reads only what you **committed** — exactly like the
> real marker — so commit before you run it.

### Step 10 — Clean up when you are done

```bash
cd infra && terraform destroy       # type: yes
```

The container and the network are removed; the image stays on your laptop
(`keep_locally = true`). The state file is now almost empty — and still never committed.

---

## Part B — Ansible (about 20 minutes)

Pick **one** place to run it:

| You have | Run it |
|---|---|
| Ubuntu (WSL), macOS or Linux, with Ansible installed | in your terminal, in your project folder |
| Windows without WSL | **Killercoda** in your browser, or **a GitHub runner** — see below |
| No time to install anything | **a GitHub runner** — the workflow runs the playbook twice for you |

### Step 11 — Copy the playbook and fill three blanks

```bash
cp -r ~/inf345-week11-lab/starter/ansible .
```

`ansible/inventory.ini` lists one group with one machine: this computer. `ansible/site.yml`
has three blanks:

- **1** `hosts:` — the group name from `inventory.ini`, without the brackets.
- **2** `ansible.builtin.____:` — the module that manages files **and directories**.
- **3** `notify:` — the **exact** name of the handler at the bottom (copy it).

### Step 12 — Run it twice

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml --syntax-check
ansible-playbook -i ansible/inventory.ini ansible/site.yml
ansible-playbook -i ansible/inventory.ini ansible/site.yml
```

> **Checkpoint.** The `PLAY RECAP` line of the first run says `changed=3` (the folder, the
> file and the handler). The second run says `ok=3 changed=0`. Then
> `cat ~/inf345-app/restarts.log` shows **one** line: the handler ran only when something
> changed. That is idempotency.

### Step 13 — Ask before you change

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml --check --diff -e app_port=9090
cat ~/inf345-app/app.env            # still PORT=8080
```

> **Checkpoint.** A diff with `-PORT=8080` and `+PORT=9090`, and `changed=1` — but the file
> did not change. `--check` asks "what would you do?"; `--diff` shows the lines. It is
> Ansible's `plan`.

Commit `ansible/` on your branch when it works.

### On Killercoda (no install, in the browser)

Open **killercoda.com/playgrounds/scenario/ubuntu** and sign in. You get an Ubuntu machine as
`root` for up to an hour; everything is deleted when the session ends, so push your files
first (from Windows you can create them in GitHub's web editor: **Add file → Create new
file**). Then, in the Killercoda terminal:

```bash
apt-get update -qq && apt-get install -y -qq pipx git
pipx install ansible-core && export PATH="$PATH:/root/.local/bin"
git clone https://github.com/<you>/<your-project>.git && cd <your-project>
git switch infra                    # the branch that has ansible/
ansible-playbook -i ansible/inventory.ini ansible/site.yml
ansible-playbook -i ansible/inventory.ini ansible/site.yml
```

### On a GitHub runner (nothing to install at all)

```bash
mkdir -p .github/workflows
cp ~/inf345-week11-lab/starter/.github/workflows/ansible.yml .github/workflows/
git add .github/workflows/ansible.yml ansible/ && git commit -m "Run the playbook twice in CI" && git push
```

Actions → **Ansible** → the job **Run the playbook twice**: a syntax check, a first run, and a
second run that **fails if anything changed**. It checks the recap line, not only the exit
code — because Ansible exits with 0 even when it matched no hosts at all (Week 4's green lie,
in another tool).

---

## How M6's infrastructure half is marked

Week 12's M6 marker runs these checks on **the last commit on your default branch before
Sunday 6 December, 23:59**, on a GitHub runner, from a fresh clone. `check_iac.py` is the same
code: run it with `--tool terraform` and you see what the marker sees.

**Gates — any failure scores the whole of M6 zero:**

- `infra/` contains Terraform: at least one committed `infra/*.tf` file.
- **No Terraform state or provider cache in any commit, ever:** no `*.tfstate`, no
  `*.tfstate.*` (such as `.tfstate.backup`), nothing under `.terraform/`. Deleting it later
  does not remove it from the history.
- No credentials anywhere in the history — the same check as M1–M5.

**25 points — "the infrastructure is code"** (all of it, or the list of what is missing):

| Check | In plain words |
|---|---|
| `terraform init`, `validate`, `fmt -check` and `plan` succeed | the marker runs them with no `-var` flags and no state |
| the plan creates at least one resource | your code describes something |
| `kreuzwerker/docker` is required with a version constraint that has an upper bound | `~> 4.6` yes; `>= 4.0` no (it would accept 5.0) |
| every `variable` has a non-empty `description`, and every variable has a `default` | the marker cannot type values for you |
| only the Docker provider; modules only from local folders; no remote `backend` or `cloud` block | the marker runs `plan` on a throwaway machine with no credentials |
| `infra/.terraform.lock.hcl` is committed, lists `kreuzwerker/docker`, and its version meets your constraint | pin what you borrow — and commit the pin |
| no `____` blank left in any `.tf` file | |

**Not checked:** which image you run (the rescue image is fine), whether you ran `apply`, and
Ansible.

**And one thing no script checks:** in Tuesday sessions I open a few repositories and ask the
owner about one line. "Why does `image = docker_image.app.image_id` create an order?" "What
does `~> 4.6` allow?" "Why is the lock file committed and the state not?" If you filled the
blanks yourself, you know.

Late work follows the course rule: 10 points per started day, down to a floor of 50. Push,
then email me the repository link.

---

## No Docker on your laptop?

- **Steps 1–5 and 9 work without Docker.** `plan` on a fresh folder never contacts Docker
  (the provider connects only when it creates, reads or changes something). The checker's
  `--tool terraform` runs `plan` the same way, so you can reach 25/25 without Docker.
- **For `apply` (Steps 6–8), use a GitHub runner, which has Docker:** copy
  `starter/.github/workflows/terraform.yml` to `.github/workflows/`, push, then Actions →
  **Terraform** → **Run workflow**. A manual run applies your configuration on the runner,
  calls `/healthz`, and destroys everything again. Read the plan and the `curl` result in the
  log. The runner is thrown away, and its state with it — a good picture of why state needs a
  real home.

---

<details>
<summary><b>Common failures</b> (open when you see an error)</summary>

**`Error: Invalid provider type`** or **`Error: Invalid version constraint`** (on
`versions.tf` line 7 or 9)
→ Blank 1 or 2 is still `____`.
→ `source = "kreuzwerker/docker"`, `version = "~> 4.6"`. (Terraform's wording may differ
slightly from OpenTofu's; the line number is what matters.)

**`Error: Invalid reference`** … `image   = ____` … *A reference to a resource type must be
followed by at least one attribute access*
→ Blank 5, 6 or 7 is still `____`, or you wrote only `docker_image`.
→ The full shape is `docker_image.app.image_id`: type, name, attribute.

**`Error: Reference to undeclared resource`** … *A managed resource "docker_network" "notes"
has not been declared in the root module.*
→ The name in your reference does not match the name in the `resource` line. The scaffold's
resources are called `app`, not `notes` (Monday's demo used `notes`).
→ `docker_network.app.name`.

**`Error: Unsupported argument`** … *An argument named "descripton" is not expected here. Did
you mean "description"?*
→ A typo. Terraform names the line and suggests the right word. Read it before you search.

**`Error: failed to create Docker client: Error pinging Docker server, please make sure that
unix:///var/run/docker.sock is reachable`** … *Cannot connect to the Docker daemon … Is the
docker daemon running?*
→ Docker Desktop is not running, or (macOS) the provider looks for a socket that Docker
Desktop did not create. On Windows the address in the message is
`npipe:////./pipe/docker_engine`.
→ Start Docker Desktop and check `docker ps`. On macOS, run the `export DOCKER_HOST=…` line
from Step 6 in the same terminal.

**`permission denied while trying to connect to the Docker daemon socket`** (Linux)
→ Your user is not in the `docker` group.
→ `sudo usermod -aG docker $USER`, log out and in again, then `docker ps`.

**`Error: Unable to read Docker image into resource: unable to pull image ghcr.io/…`** followed
by `denied`, `unauthorized`, `manifest unknown` or `invalid reference format`
→ `denied`/`unauthorized`: the package is private, or the name is wrong — it must be
lowercase. `manifest unknown`: that tag does not exist — copy the SHA from the package page.
`invalid reference format`: a `<` or a capital letter is still in blank 4.
→ Check with `docker pull <the same name>` after `docker logout ghcr.io`.

**`… no matching manifest for linux/arm64/v8 in the manifest list entries`** (Apple-silicon Mac)
→ Your CI builds `linux/amd64` images (Week 6). The `platform = "linux/amd64"` line in
`main.tf` tells Docker to pull that one and emulate it. You deleted that line.
→ Put it back.

**`Error: Unable to create container: … NotFound: content digest sha256:…: not found`**
(Apple-silicon Mac)
→ Your image has an Intel and an Apple copy (the rescue image does). Terraform pulled only
the `linux/amd64` one, then Docker looked for the Apple copy to create the container.
→ The container needs `platform = "linux/amd64"` too. Copy the `platform` line and the
`lifecycle` block under `env` from the starter's `main.tf` into yours, then `terraform apply`
again.

**`Error: Unable to create container: Error response from daemon: Conflict. The container
name "/inf345-app" is already in use`**
→ An `inf345-app` container exists that Terraform did not create (an earlier `docker run`, or
a state file you deleted). Terraform never adopts a container it did not make.
→ `docker rm -f inf345-app`, then `terraform apply` again.

**`Error: Unable to start container: … Bind for 0.0.0.0:8080 failed: port is already allocated`**
→ Something else on your laptop uses port 8080 (often a container from Week 6 Compose).
→ `docker ps` and stop it, or use another port: `terraform apply -var host_port=8081`. The
half-created container is replaced on the next apply.

**`Error: Failed to resolve provider packages`** … *locked provider
registry.terraform.io/kreuzwerker/docker 4.5.0 does not match configured version constraint
~> 4.6; must use terraform init -upgrade*
→ You changed the constraint after the lock file was written.
→ `terraform init -upgrade`, then commit the new `.terraform.lock.hcl`.

**The checker: `infra/.terraform.lock.hcl is not committed`**
→ `git add infra/.terraform.lock.hcl` and commit. If `git add` says the file is ignored, an
old line in your `.gitignore` names it (an older version of this course said to ignore it):
delete that line.

**The checker: `[gate FAIL] no state in Git: Terraform state or cache is in the history`**
→ A state file or `.terraform/` was committed at some point. Deleting it in a later commit is
not enough: it is still in the history, and a state file can hold secrets.
→ If it held anything secret, change that secret first. Then rewrite the history (install
`git-filter-repo` with `pipx install git-filter-repo` or `sudo apt install git-filter-repo`):
```bash
git filter-repo --invert-paths --path-glob '*.tfstate' --path-glob '*.tfstate.*' \
  --path-glob '*/.terraform/*' --path-glob '.terraform/*' --force
git remote add origin https://github.com/<you>/<your-project>.git    # filter-repo removes it
git push --force origin --all
```
Then run the checker again. Ask in the chat first if you are unsure — this rewrites history.

**`ansible-playbook: command not found`** right after `pipx install`
→ The folder pipx installs into is not on your `PATH` yet.
→ `pipx ensurepath`, then open a new terminal (or `export PATH="$PATH:$HOME/.local/bin"`).

**`[WARNING]: Could not match supplied host pattern, ignoring: …`** and **`skipping: no hosts
matched`** — with exit code 0
→ Blank 1 does not match the group in `inventory.ini`, or you forgot `-i ansible/inventory.ini`
("No inventory was parsed, only implicit localhost is available"). Nothing ran, and Ansible
still exits with 0.
→ Fix the group name or add `-i`. Read the recap line, not only the exit code.

**`[ERROR]: The requested handler 'Restart app' was not found in either the main handlers list
nor in the listening handlers list`**
→ Blank 3 is not exactly the handler's name.
→ Copy the name from the `- name:` line under `handlers:`: `Restart the app`.

**`[ERROR]: YAML parsing failed: Colons in unquoted values must be followed by a non-space
character.`** (with a line and column)
→ An indentation or colon mistake, usually around blank 2.
→ Make the line exactly `      ansible.builtin.file:` — six spaces, the module name, a colon.

**`[ERROR]: Task failed: … 'app_prot' is undefined`**
→ A typo in a variable name inside `{{ }}`.
→ The variable is `app_port`, defined under `vars:`.

**`[WARNING]: Ansible is being run in a world writable directory (/mnt/c/…), ignoring it as an
ansible.cfg source.`** (WSL)
→ Your project is on the Windows drive (`/mnt/c/…`). It still runs, but it is slow and file
permissions there are odd.
→ Clone your project inside Linux (`cd ~ && git clone …`) and work there.

**The second run says `changed=1`, not `changed=0`**
→ One task is not idempotent — usually a `shell` or `command` task you added, or a template
with a date in it.
→ Use a module (`copy`, `file`, `lineinfile`, `template`) that checks before it changes.

</details>

---

## Stuck?

Try in this order:

1. Read the **first** error, all of it: Terraform prints the file, the line and the problem.
   Nine times out of ten the cause is on that line.
2. Compare your file with the scaffold, character by character: the blanks first, then the
   names (`app`), then the quotes.
3. Open *Common failures* above.
4. Run the checker: it names the file, the line and the problem, all at once.
5. In the session: paste the error **text** in the chat, not a photo.

After the session, email with `INF 345` and your group in the subject, from your
`@sdu.edu.kz` address. Include **the link to your repository** and the error copied as text
(and the command you ran). A link gets an answer the same day; "it doesn't work" gets a
question back.

---

<details>
<summary><b>Stretch goals (not marked)</b></summary>

### 1. OpenTofu, the same files

Install OpenTofu, then in a **copy** of your folder (so your committed lock file stays as it is):

```bash
cp -r infra /tmp/infra-tofu && cd /tmp/infra-tofu && rm -rf .terraform
tofu init && tofu plan
head -5 .terraform.lock.hcl          # registry.opentofu.org/kreuzwerker/docker
```

Same language, same provider, same plan. Only the registry host in the lock file changes.

### 2. A pipeline that reads your plan

```bash
mkdir -p .github/workflows
cp ~/inf345-week11-lab/starter/.github/workflows/terraform.yml .github/workflows/
```

On every push that touches `infra/`, it runs `fmt -check`, `init`, `validate` and `plan`.
`hashicorp/setup-terraform` is pinned to a full commit SHA (v4.0.1) and Terraform to 1.16.4 —
pin what you borrow. **Run workflow** by hand also applies it on the runner, calls `/healthz`
and destroys it. Open a pull request that changes `host_port` and read the `-/+` in the log.

### 3. Your graph as a picture

```bash
cd infra && terraform graph -format=mermaid
```

(Terraform 1.16 or newer.) Paste the output into your README between ```` ```mermaid ````
fences. GitHub draws it: three boxes and the arrows your references created.

### 4. Guard rails

- Add a `validation` block to `restart_policy` so that only `no`, `on-failure`, `always` and
  `unless-stopped` are accepted — Monday's demo repository has one in `infra/variables.tf`.
  Then try `terraform plan -var restart_policy=sometimes` and read your own error message.
- Add `lifecycle { prevent_destroy = true }` to `docker_network.app` and run
  `terraform destroy`. Read the error. Remove it again.

### 5. Break idempotency on purpose

Add a task to `ansible/site.yml`:

```yaml
    - name: Append the port the wrong way
      ansible.builtin.shell: echo "PORT={{ app_port }}" >> "{{ app_dir }}/app-wrong.env"
```

Run the playbook twice: `changed=1` every time, and the file grows. Then install the linter
(`pipx install ansible-lint`) and run `ansible-lint ansible/site.yml`: it fails with
`no-changed-when`. Delete the task.

</details>
