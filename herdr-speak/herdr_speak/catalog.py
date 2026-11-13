"""Languages, voices, and the pinned Kokoro model files."""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from typing import Dict, List, Optional

# Kokoro-82M ONNX export, pinned to one revision so every install gets the same files.
KOKORO_REPO = "onnx-community/Kokoro-82M-v1.0-ONNX"
KOKORO_REVISION = "1939ad2a8e416c0acfeecc08a694d14ef25f2231"
KOKORO_BASE_URL = f"https://huggingface.co/{KOKORO_REPO}/resolve/{KOKORO_REVISION}"
SAMPLE_RATE = 24000

# name -> (remote path, size in bytes, sha256)
KOKORO_MODELS = {
    "full": ("onnx/model.onnx", 325532232, "8fbea51ea711f2af382e88c833d9e288c6dc82ce5e98421ea61c058ce21a34cb"),
    "small": ("onnx/model_quantized.onnx", 92361116, "fbae9257e1e05ffc727e951ef9b9c98418e6d79f1c9b6b13bd59f5c9028a1478"),
}
KOKORO_TOKENIZER = ("tokenizer.json", 3497, "77a02c8e164413299b4b4c403b14f8e0e1c1b727db4d46a09d6327b861060a34")
VOICE_SIZE = 522240

LANGUAGES: Dict[str, dict] = {
    "en-us": {
        "name": "English (US)", "kokoro": "a", "espeak": None, "say_locale": "en_US", "default_say": "Samantha",
        "code": "Code block skipped.", "table": "Table skipped.", "link": "link", "in": "in",
        "needs_input": "needs your input.", "sample": "This is {voice}. Agent responses will sound like this.",
    },
    "en-gb": {
        "name": "English (UK)", "kokoro": "b", "espeak": None, "say_locale": "en_GB", "default_say": "Daniel",
        "code": "Code block skipped.", "table": "Table skipped.", "link": "link", "in": "in",
        "needs_input": "needs your input.", "sample": "This is {voice}. Agent responses will sound like this.",
    },
    "es": {
        "name": "Spanish", "kokoro": "e", "espeak": "es", "say_locale": "es_", "default_say": "Mónica",
        "code": "Bloque de código omitido.", "table": "Tabla omitida.", "link": "enlace", "in": "en",
        "needs_input": "necesita tu respuesta.", "sample": "Esta es la voz {voice}. Así sonarán las respuestas.",
    },
    "fr": {
        "name": "French", "kokoro": "f", "espeak": "fr-fr", "say_locale": "fr_", "default_say": "Thomas",
        "code": "Bloc de code ignoré.", "table": "Tableau ignoré.", "link": "lien", "in": "dans",
        "needs_input": "a besoin de votre réponse.", "sample": "Voici la voix {voice}. Les réponses sonneront ainsi.",
    },
    "it": {
        "name": "Italian", "kokoro": "i", "espeak": "it", "say_locale": "it_", "default_say": "Alice",
        "code": "Blocco di codice omesso.", "table": "Tabella omessa.", "link": "link", "in": "in",
        "needs_input": "ha bisogno di una tua risposta.", "sample": "Questa è la voce {voice}. Le risposte suoneranno così.",
    },
    "pt-br": {
        "name": "Portuguese (Brazil)", "kokoro": "p", "espeak": "pt-br", "say_locale": "pt_BR", "default_say": "Luciana",
        "code": "Bloco de código omitido.", "table": "Tabela omitida.", "link": "link", "in": "em",
        "needs_input": "precisa da sua resposta.", "sample": "Esta é a voz {voice}. As respostas vão soar assim.",
    },
    "hi": {
        "name": "Hindi", "kokoro": "h", "espeak": "hi", "say_locale": "hi_IN", "default_say": "Lekha",
        "code": "कोड छोड़ा गया।", "table": "तालिका छोड़ी गई।", "link": "लिंक", "in": "में",
        "needs_input": "को आपके जवाब की ज़रूरत है।", "sample": "यह {voice} आवाज़ है।",
    },
}
DEFAULT_LANGUAGE = "en-us"

# How tables and symbols are spoken, per language. {size} is "5 rows"; {columns} the header names.
_ENGLISH_SPEECH = {
    "row": "row", "rows": "rows",
    "table_intro": "Table, {size}. Columns: {columns}.",
    "table_intro_wide": "Table, {size}, {count} columns, starting with {columns}.",
    "table_intro_plain": "Table, {size}.",
    "table_more": "And {count} more {rows}.",
    "table_end": "End of table.",
    "table_skipped": "Table with {size}, skipped.",
    "yes": "yes", "no": "no", "warning": "warning", "not_applicable": "not applicable",
    "milliseconds": "milliseconds", "about": "about", "plus_minus": "plus or minus", "to": "to", "change": "change",
}
SPEECH_WORDS = {
    "en-us": _ENGLISH_SPEECH,
    "en-gb": _ENGLISH_SPEECH,
    "es": {
        "row": "fila", "rows": "filas",
        "table_intro": "Tabla, {size}. Columnas: {columns}.",
        "table_intro_wide": "Tabla, {size}, {count} columnas, empezando por {columns}.",
        "table_intro_plain": "Tabla, {size}.",
        "table_more": "Y {count} {rows} más.",
        "table_end": "Fin de la tabla.",
        "table_skipped": "Tabla de {size}, omitida.",
        "yes": "sí", "no": "no", "warning": "advertencia", "not_applicable": "no aplica",
        "milliseconds": "milisegundos", "about": "aproximadamente", "plus_minus": "más o menos", "to": "a",
        "change": "cambio",
    },
    "fr": {
        "row": "ligne", "rows": "lignes",
        "table_intro": "Tableau, {size}. Colonnes : {columns}.",
        "table_intro_wide": "Tableau, {size}, {count} colonnes, à commencer par {columns}.",
        "table_intro_plain": "Tableau, {size}.",
        "table_more": "Et {count} autres {rows}.",
        "table_end": "Fin du tableau.",
        "table_skipped": "Tableau de {size}, ignoré.",
        "yes": "oui", "no": "non", "warning": "attention", "not_applicable": "non applicable",
        "milliseconds": "millisecondes", "about": "environ", "plus_minus": "plus ou moins", "to": "vers",
        "change": "variation",
    },
    "it": {
        "row": "riga", "rows": "righe",
        "table_intro": "Tabella, {size}. Colonne: {columns}.",
        "table_intro_wide": "Tabella, {size}, {count} colonne, a partire da {columns}.",
        "table_intro_plain": "Tabella, {size}.",
        "table_more": "E altre {count} {rows}.",
        "table_end": "Fine della tabella.",
        "table_skipped": "Tabella di {size}, omessa.",
        "yes": "sì", "no": "no", "warning": "attenzione", "not_applicable": "non applicabile",
        "milliseconds": "millisecondi", "about": "circa", "plus_minus": "più o meno", "to": "a", "change": "variazione",
    },
    "pt-br": {
        "row": "linha", "rows": "linhas",
        "table_intro": "Tabela, {size}. Colunas: {columns}.",
        "table_intro_wide": "Tabela, {size}, {count} colunas, começando por {columns}.",
        "table_intro_plain": "Tabela, {size}.",
        "table_more": "E mais {count} {rows}.",
        "table_end": "Fim da tabela.",
        "table_skipped": "Tabela com {size}, omitida.",
        "yes": "sim", "no": "não", "warning": "atenção", "not_applicable": "não se aplica",
        "milliseconds": "milissegundos", "about": "cerca de", "plus_minus": "mais ou menos", "to": "para",
        "change": "variação",
    },
    "hi": {
        "row": "पंक्ति", "rows": "पंक्तियाँ",
        "table_intro": "तालिका, {size}। कॉलम: {columns}।",
        "table_intro_wide": "तालिका, {size}, {count} कॉलम, पहले {columns}।",
        "table_intro_plain": "तालिका, {size}।",
        "table_more": "और {count} {rows}।",
        "table_end": "तालिका समाप्त।",
        "table_skipped": "{size} की तालिका छोड़ी गई।",
        "yes": "हाँ", "no": "नहीं", "warning": "चेतावनी", "not_applicable": "लागू नहीं",
        "milliseconds": "मिलीसेकंड", "about": "लगभग", "plus_minus": "प्लस या माइनस", "to": "से", "change": "बदलाव",
    },
}

# Recommended first choice per language (the best-rated voice of each in Kokoro's VOICES.md).
DEFAULT_KOKORO_VOICE = {
    "a": "af_heart", "b": "bf_emma", "e": "ef_dora", "f": "ff_siwis", "i": "if_sara", "p": "pf_dora", "h": "hf_alpha",
}

KOKORO_VOICES: Dict[str, str] = {
    "af_alloy": "c4a6b876047fd7fb472edf4ebd63cfac7c3b958a7cae7c106e8f038ca6308c45",
    "af_aoede": "4a004c33430762e2461eedb2013fad808ef4ab3121f5300f554476caf58d8361",
    "af_bella": "f69d836209b78eb8c66e75e3cda491e26ea838a3674257e9d4e5703cbaf55c8b",
    "af_heart": "d583ccff3cdca2f7fae535cb998ac07e9fcb90f09737b9a41fa2734ec44a8f0b",
    "af_jessica": "a240a5e3c15b43563d6e923bdca8ef5613a23471d9b77653694012435df23bd8",
    "af_kore": "9be5221b6a941c04b561959b8ff0b06e809444dcc4ab7e75a7b23606f691819e",
    "af_nicole": "cd2191ab31b914ed7b318416b0e4440fdf392ddad9106a060819aa600a64f59a",
    "af_nova": "18778272caa0d0eebaea251c35fd635f038434f9eee5e691d02a174bd328414f",
    "af_river": "00a2bcf82b1d86e8f19902ede58c65ccf6c0e43b44b7d74fad54e5d8933c9c30",
    "af_sarah": "4409fbc125afabacc615d94db5398d847006a737b0247d6892b7a9a0007a2f0a",
    "af_sky": "4435255c9744f3f31659e0d714ab7689bf65d9e77ec1cce060f083912614f0b9",
    "am_adam": "162b035ed91cfc48b6046982184c645f72edcdd1b82843347f605d7bf7b15716",
    "am_echo": "3968b92c3c4cd1c4416dbded36c13eaa388a90d5788d02a13e4d781f5f8cf3c3",
    "am_eric": "e8b5be17edd1e3636901ce7598baafe2dc8dd8ff707a0c23bf9e461add7e2832",
    "am_fenrir": "c27989f741f7ee34d273a39d8a595cc0837d35f5ced9a29b7cc162614616df43",
    "am_liam": "52403be32fd047c6a44517cb0bcd6b134f2a18baa73e70ef41651e0eab921ade",
    "am_michael": "1d1f21dd8da39c30705cd4c75d039d265e9bc4a2a93ed09bc9e1b1225eb95ba1",
    "am_onyx": "da5d135b424164916d75a68ffb4c2abce3d7d5ccc82dd1ee6cf447ce286145e6",
    "am_puck": "fcf73c989033e9233e0b98713eca600c8c74dcc1614b37009d5450ff4a2274a0",
    "am_santa": "61150cf726ab6c5ed7a99f90a304f91f5a72c00c592e89ec94e5df11c319227a",
    "bf_alice": "08afa6ba24da61ea5e8efa139e5aadc938d83f0a6da5a900adaf763ac1da5573",
    "bf_emma": "669fe0647f9dd04fcab92f1439a40eeb4c8b4ab1f82e4996fe3d918ce4a63b73",
    "bf_isabella": "3754352c4aaa46d17f27654ab7518d65b62ad6163a0f55a5f4330c2da2c4e94f",
    "bf_lily": "5e0ee32ebe64a467124976b14e69590746f1c4ce41a12b587a50c862edfea335",
    "bm_daniel": "6b3194bbceffb746733cbc22c8f593dd44e401a71d53895a2dca891bc595a1e8",
    "bm_fable": "f889083196807b4adb15e9204252165f503b8d33d3982e681c52443c49d798f1",
    "bm_george": "c4b235a4c1f2cd3b939fed08b899ce9385638b763f7b73a59616c4fc9bd6c9bc",
    "bm_lewis": "b8f671cef828c30e66fdf0b0756a76bba58f6bb3398cbbf27058642acbcedb97",
    "ef_dora": "f66ec66bd295acb18372e37008533a9a3228483ccd294e7538d5d9294ac9a532",
    "em_alex": "27809e9eafdcbcfff90a3016c697568676531de2a2c39cee29c96c7bd6b83e95",
    "em_santa": "ad43b774e1ca24d05c6161297d8aeb770ac3d29bb95daf516727af5f7d543683",
    "ff_siwis": "a35f5675ad08948e326ae75fd0ea16ba5d0042e4f76b5f3d1df77d0a48c54861",
    "hf_alpha": "040be6a4425411cc01fda5fd06693c76bfa78572632852bc8cda9c99232ffb56",
    "hf_beta": "cd83ae0bb9b2e4e4fb92b4973bd8d1822ca0036d3c498bf4fc89aa8e33917cc7",
    "hm_omega": "b02d9222d9ed00ce26b302173a862c2c93f96cc40b5c422b8d14910b9ff34137",
    "hm_psi": "644daf88ba8aeb7bd08950bbdcd4453bb280864e49dc4df93fabc6be32e03f37",
    "if_sara": "409b69248798fcdc2542330c76953d230710f19b057e59cb82fdc3c4cf71265c",
    "im_nicola": "bc578e510d52a96d6940d46f12e96d7b3df00905dbea075113226d100e6e1ab0",
    "jf_alpha": "56b479360aad9f367aeb8cef908f9201cf48b4555e488c5f4590c9dfcd978bb6",
    "jf_gongitsune": "0f1181f3772d27b7c12aaf4bcd71e31b186c4146e330d074a3dc64ee392af396",
    "jf_nezumi": "13cb71eebb0b48739d444558322aa35a8c9a489b80e1e631f14d2e6aea93026b",
    "jf_tebukuro": "29c6c0561b4288d59639677bebe7533c919743d5ea68d0d2ae992644beea6696",
    "jm_kumo": "09e959d239724c734d65661f06f14cdabcddfd476bfaaad905a937099ae9e64f",
    "pf_dora": "3da7b5b2d91847ebf5646f57631af6ececae3c29a89cd300f06edf9aa6cfe9ee",
    "pm_alex": "0175c753f59c54e7fd5a995bedef0c5ff2fb67e0043dd3dcb2ae74ec2acbeb2a",
    "pm_santa": "8b012db3185778afe2e45a62cbad69db73021774fe68dda634bcc748a982eede",
    "zf_xiaobei": "5dde6e1c9c4f12c8b327bc29c0cee361a23b52b952c04636858ba637ec66e640",
    "zf_xiaoni": "08892b62a39af0a615cd0581238db7e19e44c578e8fa0bfd0e586e93327d9cba",
    "zf_xiaoxiao": "03adb5d5e3ddd88b047954e974e651cb0a4b524c985057e5d872e962c7be1169",
    "zf_xiaoyi": "bc1555c5c486099196ac254bae5e0bb543c121952a3092f50b7d8724f1bc36b3",
    "zm_yunjian": "de48a00bdbf3649f07162269a2b6e0513604389bfac8a2e6c75cb34b323ad6fa",
    "zm_yunxi": "7243892fb4e560d47014090ddf010f8b8b790f3c6b029ff82b2ac06aa4e27c8b",
    "zm_yunxia": "6b2b8fc15b3df19a368daebe5c581c7fabf433ee5b8a17ffd6b3d723cff8936d",
    "zm_yunyang": "261e2c89470534dbbcb8fd98b8fdc495ec94063d9bb6c8277f7be43cccba3f42",
}


def language(code: Optional[str]) -> dict:
    """The language's settings and phrases, including how it speaks tables and symbols."""
    code = code if code in LANGUAGES else DEFAULT_LANGUAGE
    return {**SPEECH_WORDS[code], **LANGUAGES[code]}


def language_code(code: Optional[str]) -> str:
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def kokoro_voices_for(code: Optional[str]) -> List[str]:
    prefix = language(code)["kokoro"]
    return sorted(name for name in KOKORO_VOICES if name.startswith(prefix))


def default_kokoro_voice(code: Optional[str]) -> str:
    return DEFAULT_KOKORO_VOICE[language(code)["kokoro"]]


def voice_description(name: str) -> str:
    """'af_heart' -> 'Heart (female)'."""
    gender = {"f": "female", "m": "male"}.get(name[1:2], "")
    return f"{name[3:].capitalize()} ({gender})" if gender else name


_SAY_LINE = re.compile(r"^(?P<name>.+?)\s+(?P<locale>[a-z]{2}_[A-Z]{2})\s+#(?P<sample>.*)$", re.M)
_LANGUAGE_SUFFIX = re.compile(r" \((?:[^()]|\([^()]*\))*\)$")  # " (English (UK))"
# Apple's sound-effect voices; they make poor readers.
NOVELTY_VOICES = {
    "Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Deranged", "Fred", "Good News", "Hysterical",
    "Jester", "Junior", "Kathy", "Organ", "Pipe Organ", "Ralph", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox",
}
# Compact multilingual voices, listed after the language's own voices.
ELOQUENCE_VOICES = {"Eddy", "Flo", "Grandma", "Grandpa", "Reed", "Rocko", "Sandy", "Shelley"}


@lru_cache(maxsize=1)
def _say_listing() -> str:
    """`say -v ?` takes about half a second; the panel redraws twice a second, so ask once."""
    return subprocess.run(["/usr/bin/say", "-v", "?"], capture_output=True, text=True).stdout


def say_voices_for(code: Optional[str], listing: Optional[str] = None) -> List[str]:
    """Installed macOS voices for the language: the default first, then its own voices, then multilingual ones.

    Skips novelty voices and Siri voices, which `say` can't use from processes Herdr starts.
    """
    if listing is None:
        listing = _say_listing()
    locale = language(code)["say_locale"]
    usable, siri = set(), set()
    for match in _SAY_LINE.finditer(listing):
        if not match.group("locale").startswith(locale):
            continue
        # Older macOS lists "Alice"; newer lists "Daniel (English (UK))" and "Ava (Premium) (English (US))".
        name = _LANGUAGE_SUFFIX.sub("", match.group("name").strip())
        if name in NOVELTY_VOICES:
            continue
        (siri if "Siri" in match.group("sample") else usable).add(name)
    default = language(code)["default_say"]
    return sorted(usable, key=lambda name: (name != default, name in ELOQUENCE_VOICES, name))
