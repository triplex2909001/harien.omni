#!/usr/bin/env python3
"""Word Origin 2D Engine for GitHub Actions (OmniVoice harien.omni & Hyperframes harien.render).
Google Drive (aleron.dt:) is the Single Source of Truth (SSOT):
- Posts Folder ID: 19p_SWDErDYluix6g6Qg9f8lCCmALHjMQ
- Hanario Root Folder ID: 1JA4bGZ4pMn0BquMAOTyp8geDsbTyF80w
Strict Voice Rules:
- Thuy Duong (thuy_duong_20yo_female_vi.wav): ONLY speaks Vietnamese (1.0x) in s01 hook for A1-B1.
- Single English Voice in body (s02, s03a, s03b, s04, cta):
  * A1-A2: 100% Rio (rio_6yo_male_en.wav, slow EN 0.85x)
  * B1: 100% Bella (bella_25yo_female_en.wav, slow EN 0.85x)
  * B2+: Bella/Hana (monolingual EN 0.95x)
Rule: File length <= 150 lines (AGENTS.md).
"""
import datetime, inspect, json, os, re, shutil, struct, subprocess, wave

POSTS_FOLDER_ID = os.environ.get("GDRIVE_POSTS_FOLDER_ID", "19p_SWDErDYluix6g6Qg9f8lCCmALHjMQ")
HANARIO_ROOT_ID = os.environ.get("GDRIVE_HANARIO_FOLDER_ID", "1JA4bGZ4pMn0BquMAOTyp8geDsbTyF80w")
SCENE_KEYS = ["s01", "s02", "s03a", "s03b", "s04", "cta"]
_MODEL_CACHE = None

REF_VOICE_MAP = {
    "bella": ("assets/voice_samples/canonical_6_voices/bella_25yo_female_en.wav", "assets/voice_samples/canonical_6_voices/bella_25yo_female_en.txt"),
    "hana": ("assets/voice_samples/canonical_6_voices/hana_10yo_female_en.wav", "assets/voice_samples/canonical_6_voices/hana_10yo_female_en.txt"),
    "rio": ("assets/voice_samples/canonical_6_voices/rio_6yo_male_en.wav", "assets/voice_samples/canonical_6_voices/rio_6yo_male_en.txt"),
    "thuy_duong": ("assets/voice_samples/canonical_6_voices/thuy_duong_20yo_female_vi.wav", "assets/voice_samples/canonical_6_voices/thuy_duong_20yo_female_vi.txt"),
}


def get_rclone_remote() -> str:
    if not shutil.which("rclone"):
        return ""
    out = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True).stdout.splitlines()
    for pref in ("aleron.dt:", "vpsg24gb.aleron.dt:"):
        if pref in out:
            return pref.rstrip(":")
    return next((l.strip().rstrip(":") for l in out if l.strip().endswith(":")), "")


def gdrive_pull_post(remote: str, post_id: str, rel_path: str, local_path: str, is_dir: bool = False) -> bool:
    if not remote:
        return os.path.exists(local_path)
    os.makedirs(local_path if is_dir else os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
    cmd = ["rclone", "copy" if is_dir else "copyto", f"{remote}:{post_id}/{rel_path}", local_path, "--drive-root-folder-id", POSTS_FOLDER_ID]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def gdrive_push_post(remote: str, post_id: str, local_path: str, rel_path: str, is_dir: bool = False) -> bool:
    if not (remote and os.path.exists(local_path)):
        return False
    cmd = ["rclone", "copy" if is_dir else "copyto", local_path, f"{remote}:{post_id}/{rel_path}", "--drive-root-folder-id", POSTS_FOLDER_ID]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def resolve_speakers_by_level(level: str) -> dict:
    lv = (level or "B2").upper().strip()
    if lv in ("A1", "A2", "A1-A2"):
        return {"mode": "Bilingual_Rio_SlowEN", "s01": ("thuy_duong", "vi", 1.0), "s02": ("rio", "en", 0.85), "s03a": ("rio", "en", 0.85), "s03b": ("rio", "en", 0.85), "s04": ("rio", "en", 0.85), "cta": ("rio", "en", 0.90)}
    if lv == "B1":
        return {"mode": "Bilingual_Bella_SlowEN", "s01": ("thuy_duong", "vi", 1.0), "s02": ("bella", "en", 0.85), "s03a": ("bella", "en", 0.85), "s03b": ("bella", "en", 0.85), "s04": ("bella", "en", 0.85), "cta": ("bella", "en", 0.90)}
    return {"mode": "Monolingual_EN", "s01": ("hana", "en", 0.95), "s02": ("bella", "en", 0.95), "s03a": ("bella", "en", 0.95), "s03b": ("bella", "en", 0.95), "s04": ("bella", "en", 0.95), "cta": ("bella", "en", 0.95)}


def strip_speaker_tag(raw_text: str) -> str:
    lines = [l.strip() for l in (raw_text or "").splitlines() if l.strip() and not l.strip().upper().startswith("[TITLE]")]
    return re.sub(r"^\[[^\]]+\]\s*:\s*", "", " ".join(lines)).strip()


def _trim_silence_and_tempo(raw_wav: str, out_wav: str, spd: float, sr: int = 24000):
    tmp_w = f"{out_wav}.norm.wav"
    af = ["highpass=f=85", "lowpass=f=11800"] + ([f"atempo={spd:.2f}"] if abs(spd - 1.0) > 0.02 else []) + ["loudnorm=I=-16:TP=-1.5:LRA=11"]
    subprocess.run(["ffmpeg", "-y", "-i", raw_wav, "-af", ",".join(af), "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", tmp_w], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with wave.open(tmp_w, "r") as wf:
        raw = wf.readframes(wf.getnframes())
        pcm = list(struct.unpack(f"<{len(raw)//2}h", raw))
    os.remove(tmp_w)
    first_i = next((i for i, v in enumerate(pcm) if abs(v) > 65), 0)
    last_i = len(pcm) - 1
    while last_i > first_i and abs(pcm[last_i]) < 65:
        last_i -= 1
    trimmed = pcm[max(0, first_i - int(0.04 * sr)) : min(len(pcm), last_i + int(0.10 * sr))]
    fade_n = min(len(trimmed), int(0.08 * sr))
    for k in range(fade_n):
        trimmed[len(trimmed) - fade_n + k] = int(trimmed[len(trimmed) - fade_n + k] * (1.0 - k / float(fade_n)))
    final_pcm = [0] * int(0.04 * sr) + trimmed + [0] * int(0.14 * sr)
    with wave.open(out_wav, "w") as wf:
        wf.setparams((1, 2, sr, len(final_pcm), "NONE", "not compressed"))
        wf.writeframes(struct.pack(f"<{len(final_pcm)}h", *final_pcm))


def _synth_omnivoice_scene(spk: str, lang: str, spd: float, text: str, wav_p: str):
    global _MODEL_CACHE
    ref_wav, ref_txt_p = REF_VOICE_MAP.get(spk, REF_VOICE_MAP["bella"])
    ref_txt = open(ref_txt_p, encoding="utf-8").read().strip() if os.path.exists(ref_txt_p) else ""
    print(f"  [RefVoice] spk={spk} lang={lang} wav={ref_wav} ({os.path.getsize(ref_wav) if os.path.exists(ref_wav) else 0}B) txt={ref_txt[:45]}...", flush=True)
    raw_out = f"{wav_p}.raw.wav"
    try:
        from scripts.omnivoice_hf_client import _synth_one, _upload_ref
        rpath = _upload_ref(ref_wav, spk)
        _synth_one(rpath, ref_txt, {"id": spk, "text": text, "lang": lang, "speed": 0.95}, raw_out)
    except Exception as e:
        print(f"[OmniVoice HF fallback to local model] {e}", flush=True)
        import numpy as np, soundfile as sf, torch
        from omnivoice import OmniVoice
        from scripts.colab_worker_payload import _extract_wav, _pad_ref_audio
        if _MODEL_CACHE is None:
            dev = "cuda:0" if torch.cuda.is_available() else "cpu"
            dt = torch.float16 if torch.cuda.is_available() else torch.float32
            _MODEL_CACHE = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=dev, dtype=dt, load_asr=False)
        sig = set(inspect.signature(_MODEL_CACHE.generate).parameters.keys())
        ptxt = text.strip() if text.strip().endswith("?") else f"{text.strip().rstrip(".!")}..."
        kw = {"text": ptxt, "ref_audio": _pad_ref_audio(ref_wav, spk), "ref_text": ref_txt}
        if "speed" in sig:
            kw["speed"] = 0.95
        if "language" in sig:
            kw["language"] = lang
        wdata = _extract_wav(_MODEL_CACHE.generate(**kw)).astype(np.float32)
        sf.write(raw_out, np.concatenate([wdata, np.zeros(7200, dtype=wdata.dtype)]), 24000)
    _trim_silence_and_tempo(raw_out, wav_p, spd)
    if os.path.exists(raw_out):
        os.remove(raw_out)


def run_omnivoice_word_origin(post_id: str, wdir: str, level: str = "B2", force: bool = True) -> list:
    remote = get_rclone_remote()
    os.makedirs(wdir, exist_ok=True)
    man_path = os.path.join(wdir, "00_post_manifest.json")
    gdrive_pull_post(remote, post_id, "00_post_manifest.json", man_path)
    manifest = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {"post_id": post_id, "level": level}
    eff_level = manifest.get("level") or level
    spk_cfg = resolve_speakers_by_level(eff_level)
    adir = os.path.join(wdir, "01_audio")
    os.makedirs(adir, exist_ok=True)
    created = []
    for sk in SCENE_KEYS:
        wav_p = os.path.join(adir, f"{sk}.wav")
        spk, lang, spd = spk_cfg[sk]
        raw_sc = manifest.get(sk) or manifest.get("scenes", {}).get(sk, {}).get("text") or ("Follow HaRiENG for daily word origins!" if sk == "cta" else f"Word Origin scene {sk} for {post_id}.")
        text = strip_speaker_tag(raw_sc if isinstance(raw_sc, str) else raw_sc.get("text", ""))
        print(f"[OmniVoice 2D] Synthesizing {post_id}/{sk}.wav ({spk}, {lang}, spd={spd}): {text}", flush=True)
        _synth_omnivoice_scene(spk, lang, spd, text, wav_p)
        if os.path.exists(wav_p):
            gdrive_push_post(remote, post_id, wav_p, f"01_audio/{sk}.wav")
            created.append(f"01_audio/{sk}.wav")
    ckpt = {"post_id": post_id, "engine": "OmniVoice@GitHubActions(harien.omni)", "level": eff_level, "pairing": spk_cfg["mode"], "files": created, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    ckpt_p = os.path.join(adir, "omnivoice_checkpoint.json")
    json.dump(ckpt, open(ckpt_p, "w", encoding="utf-8"), indent=2)
    gdrive_push_post(remote, post_id, ckpt_p, "01_audio/omnivoice_checkpoint.json")
    return created
