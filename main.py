import logging
import os
import re
from io import BytesIO
from pypdf import PdfReader
from supabase import create_client, Client

# Silenzia i warning secondari di pypdf
logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("Variabili d'ambiente SUPABASE_URL / KEY mancanti.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
BUCKET_NAME = "documents"
TARGET_TABLE = "component_proposals"

# Dizionario per il riconoscimento degli elementi costruttivi identitari
CONSTRUCTIVE_ELEMENTS_VOCAB = {
    "volta a botte": "Volte a botte",
    "volta a padiglione": "Volte a padiglione",
    "arco a tutto sesto": "Archi a tutto sesto",
    "archi": "Archi e strutture voltate",
    "muratura in tufo": "Muratura in tufo",
    "mura perimetrali": "Mura perimetrali",
    "scalinata": "Scalinata monumentale",
    "scalone": "Scalone d'onore",
    "trattaglio": "Macchinari per la trattura della seta (Trattagli)",
    "telaio": "Telai di tessitura meccanica/manuale",
    "vasca": "Vasche di immersione / Fontana",
    "fontana": "Fontana monumentale",
    "cortile": "Cortile pavimentato",
    "porticato": "Porticato ad archi",
    "colonnato": "Colonnato strutturale",
    "lesene": "Lesene e modanature di facciata",
}

# Regole di categorizzazione spaziale
CATEGORY_RULES = [
    {
        "name": "Belvedere - main hall",
        "category": "Cortile principale",
        "level": "Primo piano",
        "keywords": [
            "salone reale",
            "salone di rappresentanza",
            "salone del belvedere",
            "gran salone",
            "sala del trono",
        ],
        "confidence": 0.95,
    },
    {
        "name": "New silk factory / Belvedere",
        "category": "Cortile principale",
        "level": "Piano terra",
        "keywords": [
            "filanda reale",
            "setificio di san leucio",
            "opificio borbonico",
            "fabbrica della seta",
            "arte della seta",
            "trattaglio",
        ],
        "confidence": 0.92,
    },
    {
        "name": "Belvedere residential spaces",
        "category": "Spazio aperto",
        "level": "Primo piano",
        "keywords": [
            "quartiere san ferdinando",
            "alloggi degli operai",
            "residenza reale",
            "appartamento del re",
            "stanze reali",
        ],
        "confidence": 0.89,
    },
]


def extract_snippet(text: str, keyword: str) -> str:
    """Estrae la frase contestuale che circonda la parola chiave."""
    clean_text = re.sub(r"\s+", " ", text)
    pattern = re.compile(
        r"([^.!?]*?\b" + re.escape(keyword) + r"\b[^.!?]*[.!?])", re.IGNORECASE
    )
    match = pattern.search(clean_text)

    if match:
        return match.group(0).strip()

    idx = clean_text.lower().find(keyword.lower())
    if idx != -1:
        start = max(0, idx - 100)
        end = min(len(clean_text), idx + 150)
        return f"...{clean_text[start:end].strip()}..."

    return "Estratto non disponibile."


def detect_constructive_elements(text: str) -> str:
    """Rileva la presenza di elementi costruttivi identitari nel testo della pagina."""
    found_elements = set()
    text_lower = text.lower()

    for term, label in CONSTRUCTIVE_ELEMENTS_VOCAB.items():
        if re.search(r"\b" + re.escape(term) + r"\b", text_lower):
            found_elements.add(label)

    if found_elements:
        return ", ".join(sorted(found_elements))
    return "Elementi costruttivi specifici non menzionati esplicitamente."


def extract_and_analyze_pdf(file_path: str) -> dict:
    response = supabase.storage.from_(BUCKET_NAME).download(file_path)
    pdf_file = BytesIO(response)
    reader = PdfReader(pdf_file)

    page_scores = []

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1

        # Salta copertine/indici sintetici
        if page_num < 3 and len(reader.pages) > 5:
            continue

        text = page.extract_text() or ""
        text_lower = text.lower()

        # Estrazione elementi costruttivi presenti nella pagina
        constructive_elements = detect_constructive_elements(text)

        for rule in CATEGORY_RULES:
            for kw in rule["keywords"]:
                matches = len(re.findall(r"\b" + re.escape(kw) + r"\b", text_lower))
                if matches > 0:
                    snippet = extract_snippet(text, kw)
                    page_scores.append(
                        {
                            "page": str(page_num),
                            "rule": rule,
                            "keyword": kw,
                            "score": matches,
                            "snippet": snippet,
                            "constructive_elements": constructive_elements,
                        }
                    )

    if page_scores:
        best_match = max(page_scores, key=lambda x: x["score"])
        rule = best_match["rule"]
        page_str = best_match["page"]

        return {
            "proposed_space_name": rule["name"],
            "space_category": rule["category"],
            "spatial_level": rule["level"],
            "ai_explanation": f"Identificato '{best_match['keyword']}' con alta rilevanza a pagina {page_str}.",
            "confidence": rule["confidence"],
            "source_page_number": page_str,
            "extracted_text_snippet": best_match["snippet"],
            "constructive_elements": best_match["constructive_elements"],
        }

    return {
        "proposed_space_name": "Complesso Belvedere San Leucio",
        "space_category": "Spazio aperto",
        "spatial_level": "Piano terra",
        "ai_explanation": "Contenuto generale sul complesso monumentale.",
        "confidence": 0.80,
        "source_page_number": None,
        "extracted_text_snippet": "Nessuna frase chiave rilevata nel testo.",
        "constructive_elements": "Nessun elemento costruttivo identificato.",
    }


def process_pending_proposals():
    files = supabase.storage.from_(BUCKET_NAME).list()
    pdf_files = [f for f in files if f.get("name", "").lower().endswith(".pdf")]

    if not pdf_files:
        print("Nessun PDF nello Storage.")
        return

    for file_info in pdf_files:
        file_path = file_info["name"]

        response = (
            supabase.table(TARGET_TABLE)
            .select("id, review_status")
            .eq("source_file_path", file_path)
            .execute()
        )

        if response.data:
            proposal = response.data[0]
            proposal_id = proposal["id"]
            review_status = proposal.get("review_status")

            if review_status == "to_review":
                print(f"-> Analisi completa ed elementi costruttivi per: {file_path}")
                try:
                    analysis = extract_and_analyze_pdf(file_path)

                    update_payload = {
                        "proposed_space_name": analysis["proposed_space_name"],
                        "space_category": analysis["space_category"],
                        "spatial_level": analysis["spatial_level"],
                        "ai_explanation": analysis["ai_explanation"],
                        "confidence": analysis["confidence"],
                        "source_page_number": analysis["source_page_number"],
                        "extracted_text_snippet": analysis["extracted_text_snippet"],
                        "constructive_elements": analysis["constructive_elements"],
                        "review_status": "reviewed",
                    }

                    supabase.table(TARGET_TABLE).update(update_payload).eq(
                        "id", proposal_id
                    ).execute()
                    print(
                        f"   [OK] Pagina: {analysis['source_page_number']} | Elementi: {analysis['constructive_elements']}"
                    )
                except Exception as e:
                    print(f"   [ERRORE] {file_path}: {e}")


if __name__ == "__main__":
    process_pending_proposals()
