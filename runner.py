#!/usr/bin/env python3
import argparse, datetime, json, os, shutil, subprocess, sys, tarfile

OMNIVOICE_REPO = "k2-fsa/OmniVoice"


def get_remote() -> str:
    if not shutil.which("rclone"):
        return ""
    res = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    return next((l.strip().rstrip(":") for l in res.stdout.splitlines() if l.strip().endswith(":")), "")


def rclone_args(prod_id: str) -> list:
    return ["--drive-root-folder-id", prod_id] if prod_id else []


def gdrive_exists(remote: str, prod_id: str, rel_path: str) -> bool:
    if not (remote and prod_id):
        return False
    res = subprocess.run(["rclone", "lsf", f"{remote}:/{rel_path}", *rclone_args(prod_id)], capture_output=True, text=True)
    return res.returncode == 0 and bool(res.stdout.strip())


def gdrive_pull(remote: str, prod_id: str, rel_path: str, local_path: str) -> bool:
    if not (remote and prod_id):
        return os.path.exists(local_path)
    os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
    return subprocess.run(["rclone", "copyto", f"{remote}:/{rel_path}", local_path, *rclone_args(prod_id)], capture_output=True).returncode == 0 and os.path.exists(local_path)


def gdrive_push(remote: str, prod_id: str, local_path: str, rel_path: str) -> bool:
    if not (remote and prod_id and os.path.exists(local_path)):
        return False
    return subprocess.run(["rclone", "copyto", local_path, f"{remote}:/{rel_path}", *rclone_args(prod_id)], capture_output=True).returncode == 0


def ensure_engine(remote: str, prod_id: str):
    if os.path.exists("scripts/gha_engine_helper.py"):
        return
    tar_p = "/tmp/engine_bundle.tar.gz"
    if not gdrive_pull(remote, prod_id, "_ENGINE/engine_bundle.tar.gz", tar_p):
        raise RuntimeError("Failed to pull _ENGINE/engine_bundle.tar.gz from PRODUCTION")
    with tarfile.open(tar_p, "r:gz") as tf:
        tf.extractall(".")


def verify_omnivoice_ready():
    import omnivoice  # noqa: F401 — https://github.com/k2-fsa/OmniVoice
    print(f"[✓] Verified {OMNIVOICE_REPO} package ready.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep-id", default=os.environ.get("EP_ID", "T01_EP003_B1"))
    ap.add_argument("--level", default=os.environ.get("LEVEL", "B1"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ep_id, prod_id, remote = args.ep_id, os.environ.get("GDRIVE_PRODUCTION_FOLDER_ID", "").strip(), get_remote()
    ensure_engine(remote, prod_id)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        verify_omnivoice_ready()
    sys.path.insert(0, os.getcwd())
    from scripts.gha_engine_helper import build_omni_voice_files

    wdir, vdir = os.path.join("workspace", ep_id), os.path.join("workspace", ep_id, "voice")
    os.makedirs(vdir, exist_ok=True)
    man_local = os.path.join(wdir, "manifest.json")
    if not gdrive_pull(remote, prod_id, f"{ep_id}/manifest.json", man_local):
        cand = f"studio/episodes/{ep_id}/manifest.json"
        if os.path.exists(cand):
            shutil.copy2(cand, man_local)
            gdrive_push(remote, prod_id, man_local, f"{ep_id}/manifest.json")

    expected = ["hook.wav", "vo.wav", "outro.wav"] if ep_id.upper().startswith("T04") else ["hook.wav", "vo.wav", "st.wav"]
    if not args.force and all(gdrive_exists(remote, prod_id, f"{ep_id}/voice/{f}") for f in expected):
        for f in expected:
            print(f"[SKIP - ALREADY ON GDRIVE] {ep_id}/voice/{f}")
            gdrive_pull(remote, prod_id, f"{ep_id}/voice/{f}", os.path.join(vdir, f))
        return

    created = build_omni_voice_files(ep_id, vdir, args.level)
    ckpt = {"ep_id": ep_id, "model": OMNIVOICE_REPO, "completed": [], "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    for fname in created:
        lpath, rpath = os.path.join(vdir, fname), f"{ep_id}/voice/{fname}"
        pushed = gdrive_push(remote, prod_id, lpath, rpath)
        print(f"[OMNIVOICE SAVED TO GDRIVE={pushed}] {rpath}")
        ckpt["completed"].append(fname)
    ckpt_local = os.path.join(wdir, "voice_checkpoint.json")
    json.dump(ckpt, open(ckpt_local, "w", encoding="utf-8"), indent=2)
    gdrive_push(remote, prod_id, ckpt_local, f"{ep_id}/voice_checkpoint.json")
    print(f"[PASS] harien.omni ({OMNIVOICE_REPO}) completed tracks: {created}")


if __name__ == "__main__":
    main()
