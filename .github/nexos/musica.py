"""
Música de fondo original para los Reels (generada por código, sin derechos de terceros).

Pop suave a ~112 BPM: progresión I–V–vi–IV en Do mayor, con bajo, arpegio,
pad, bombo, aplauso y hi-hat. Varía la semilla para que cada día suene un poco distinto.
"""
import wave

import numpy as np

SR = 44100
NOTAS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def f(n, octava):
    return 440.0 * 2 ** ((NOTAS[n] + 12 * (octava + 1) - 69) / 12)


ACORDES = [("C", ["C", "E", "G"]), ("G", ["G", "B", "D"]), ("A", ["A", "C", "E"]), ("F", ["F", "A", "C"])]


def _env(n, ataque, caida):
    t = np.arange(n) / SR
    e = np.exp(-t * caida)
    a = max(1, int(ataque * SR))
    e[:a] *= np.linspace(0, 1, a)
    return e


def _tono(freq, n, armonicos=(1.0, 0.35, 0.12)):
    t = np.arange(n) / SR
    return sum(a * np.sin(2 * np.pi * freq * (k + 1) * t) for k, a in enumerate(armonicos))


def generar(segundos, path, bpm=112, semilla=0):
    rng = np.random.default_rng(semilla)
    total = int(segundos * SR)
    L = np.zeros(total)
    R = np.zeros(total)
    beat = 60.0 / bpm
    paso = beat / 2                      # corcheas
    compas = 4 * beat
    variante = rng.integers(0, 3)

    def poner(sig, inicio, gl=1.0, gr=1.0):
        i = int(inicio * SR)
        if i >= total:
            return
        j = min(total, i + len(sig))
        L[i:j] += sig[: j - i] * gl
        R[i:j] += sig[: j - i] * gr

    n_comp = int(np.ceil(segundos / compas)) + 1
    for c in range(n_comp):
        t0 = c * compas
        raiz, notas = ACORDES[c % 4]
        # pad (acorde sostenido, suave)
        npad = int(compas * SR)
        pad = sum(_tono(f(x, 4), npad, (1.0, 0.2)) for x in notas) / 3
        pad *= _env(npad, 0.25, 0.6) * 0.10
        poner(pad, t0, 0.9, 1.0)
        # bajo: tiempos 1, 2.5, 3
        for b in (0, 1.5, 2):
            nb = int(beat * 0.9 * SR)
            poner(_tono(f(raiz, 2), nb, (1.0, 0.25)) * _env(nb, 0.005, 5) * 0.32, t0 + b * beat)
        # arpegio en corcheas
        patron = [notas[0], notas[1], notas[2], notas[1]] if variante == 0 else \
                 [notas[0], notas[2], notas[1], notas[2]] if variante == 1 else \
                 [notas[2], notas[1], notas[0], notas[1]]
        for k in range(8):
            nota = patron[k % 4]
            octava = 5 if k % 4 != 3 else 6
            nn = int(paso * 1.6 * SR)
            s = _tono(f(nota, octava), nn, (1.0, 0.3, 0.1)) * _env(nn, 0.003, 7) * 0.13
            poner(s, t0 + k * paso, 0.7 if k % 2 else 1.0, 1.0 if k % 2 else 0.7)
        # batería
        for b in range(4):
            tb = t0 + b * beat
            nk = int(0.28 * SR)
            tk = np.arange(nk) / SR
            kick = np.sin(2 * np.pi * (45 + 75 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 11) * 0.55
            poner(kick, tb)
            nh = int(0.05 * SR)
            hat = np.diff(rng.standard_normal(nh + 1)) * np.exp(-np.arange(nh) / SR * 90) * 0.035
            poner(hat, tb + beat / 2, 0.8, 1.0)
            if b in (1, 3):
                nc = int(0.18 * SR)
                ruido = rng.standard_normal(nc)
                clap = (ruido - np.concatenate(([0], ruido[:-1])) * 0.6) * np.exp(-np.arange(nc) / SR * 22) * 0.08
                poner(clap, tb, 1.0, 0.9)

    mix = np.stack([L, R], axis=1)
    # suavizado (paso bajo simple) y normalización
    k = 3
    for ch in range(2):
        mix[:, ch] = np.convolve(mix[:, ch], np.ones(k) / k, mode="same")
    pico = np.max(np.abs(mix)) or 1
    mix = mix / pico * 0.8
    fi, fo = int(0.4 * SR), int(1.5 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    pcm = (mix * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path
