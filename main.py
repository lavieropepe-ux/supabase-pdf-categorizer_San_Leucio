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
    raise ValueError("Variabili SUPABASE_URL / KEY mancanti.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
BUCKET_NAME = "documents"
TARGET_TABLE = "component_proposals"

# Vocabolario per elementi costruttivi
CONSTRUCTIVE_ELEMENTS_VOCAB = {
    "volta": "Strutture voltate (volte)",
    "volte": "Strutture voltate (volte)",
    "botte": "Volta a botte",
    "padiglione": "Volta a padiglione",
    "arco": "Archi e aperture voltate",
    "archi": "Archi e aperture voltate",
    "muratura": "Muratura portante",
    "mura": "Mura perimetrali",
    "muro": "Mura perimetrali",
    "pilastro": "Pilastri e elementi verticali",
    "pilastri": "Pilastri e elementi verticali",
    "colonna": "Colonnato / Colonne",
    "colonne": "Colonnato / Colonne",
    "scalinata": "Scalinata monumentale",
    "scalone": "Scalone d'onore",
    "scala": "Corpo scala",
    "trattaglio": "Macchinari per la trattura (Trattagli)",
    "trattagli": "Macchinari per la trattura (Trattagli)",
    "telaio": "Telai di tessitura",
    "telai": "Telai di tessitura",
    "fontana": "Fontana / Vasca d'acqua",
    "fontane": "Fontana / Vasca d'acqua",
    "vasca": "Vasca di lavaggio/immersione",
    "vasche": "Vasca di lavaggio/immersione",
    "cortile": "Cortile interno / Chiostro",
    "portico": "Porticato ad archi",
    "porticato": "Porticato ad archi",
    "terrazzo": "Terrazza / Belvedere",
    "terrazza": "Terrazza / Belvedere",
    "facciata": "Facciata monumentale",
    "prospetto": "Prospetto architettonico",
    "acquedotto": "Acquedotto Carolino / Canalizzazioni",
    "bagno": "Bagno di Maria Carolina / Vasche",
}

# Regole di categorizzazione
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
            "salone",
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
            "filanda",
            "setificio",
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
            "residenza",
        ],
        "confidence": 0.89,
    },
]


def extract_snippet(text: str, keyword: str) -> str:
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
    found_elements = set()
    text_lower = text.lower()
    for term, label in CONSTRUCTIVE_ELEMENTS_VOCAB.items():
        if re.search(r"\b" + re.escape(term) + r"\b", text_lower):
            found_elements.add(label)
    return ", ".join(sorted(found_elements)) if found_elements else ""


def extract_multiple_proposals_from_pdf(file_path: str) -> list:
    """Scansiona l'intero PDF e restituisce UNA LISTA di proposte trovate nel testo."""
    response = supabase.storage.from_(BUCKET_NAME).download(file_path)
    pdf_file = BytesIO(response)
    reader = PdfReader(pdf_file)

    proposals_by_category = {}

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1

        # Salta le prime 2 pagine per evitare solitamente copertine o indici
        if page_num < 3 and len(reader.pages) > 5:
            continue

        text = page.extract_text() or ""
        text_lower = text.lower()
        constructive_str = detect_constructive_elements(text)

        for rule in CATEGORY_RULES:
            for kw in rule["keywords"]:
                if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                    cat_name = rule["name"]

                    # Se non abbiamo ancora registrato questo spazio per questo PDF, lo creiamo
                    if cat_name not in proposals_by_category:
                        proposals_by_category[cat_name] = {
                            "proposed_space_name": rule["name"],
                            "space_category": rule["category"],
                            "spatial_level": rule["level"],
                            "ai_explanation": f"Rilevato '{kw}' nel testo a pagina {page_num}.",
                            "confidence": rule["confidence"],
                            "source_pages": [str(page_num)],
                            "extracted_text_snippet": extract_snippet(
                                text, kw
                            ),
                            "constructive_elements": set(
                                constructive_str.split(", ")
                                if constructive_str
                                else []
                            ),
                        }
                    else:
                        # Se lo spazio esiste già, aggiungiamo la pagina e uniamo gli elementi costruttivi
                        if (
                            str(page_num)
                            not in proposals_by_category[cat_name][
                                "source_pages"
                            ]
                        ):
                            proposals_by_category[cat_name][
                                "source_pages"
                            ].append(str(page_num))
                        if constructive_str:
                            for elem in constructive_str.split(", "):
                                if elem:
                                    proposals_by_category[cat_name][
                                        "constructive_elements"
                                    ].add(elem)

    # Convertiamo i dati nel formato finale
    results = []
    for cat_name, data in proposals_by_category.items():
        constructive_list = sorted(list(data["constructive_elements"]))
        results.append(
            {
                "proposed_space_name": data["proposed_space_name"],
                "space_category": data["space_category"],
                "spatial_level": data["spatial_level"],
                "ai_explanation": f"Identificate molteplici occorrenze nelle pagine {', '.join(data['source_pages'][:5])}.",
                "confidence": data["confidence"],
                "source_page_number": ", ".join(data["source_pages"]),
                "extracted_text_snippet": data["extracted_text_snippet"],
                "constructive_elements": ", ".join(constructive_list)
                if constructive_list
                else "Nessun elemento specifico.",
            }
        )

    # Se non è stata trovata nessuna categoria specifica, restituiamo un record generico
    if not results:
        results.append(
            {
                "proposed_space_name": "Complesso Belvedere San Leucio",
                "space_category": "Spazio aperto",
                "spatial_level": "Piano terra",
                "ai_explanation": "Contenuto generale sul complesso monumentale.",
                "confidence": 0.80,
                "source_page_number": None,
                "extracted_text_snippet": "Nessuna frase chiave rilevata nel testo.",
                "constructive_elements": "Nessun elemento costruttivo identificato.",
            }
        )

    return results


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
            # Prendiamo la prima riga presente
            first_record = response.data[0]
            review_status = first_record.get("review_status")

            if review_status == "to_review":
                print(
                    f"-> Analisi multi-informazione in corso per: {file_path}"
                )
                try:
                    proposals = extract_multiple_proposals_from_pdf(file_path)

                    # 1. Aggiorniamo la prima riga esistente con la prima proposta estratta
                    first_proposal = proposals[0]
                    update_payload = {
                        "proposed_space_name": first_proposal[
                            "proposed_space_name"
                        ],
                        "space_category": first_proposal["space_category"],
                        "spatial_level": first_proposal["spatial_level"],
                        "ai_explanation": first_proposal["ai_explanation"],
                        "confidence": first_proposal["confidence"],
                        "source_page_number": first_proposal[
                            "source_page_number"
                        ],
                        "extracted_text_snippet": first_proposal[
                            "extracted_text_snippet"
                        ],
                        "constructive_elements": first_proposal[
                            "constructive_elements"
                        ],
                        "review_status": "reviewed",
                    }

                    supabase.table(TARGET_TABLE).update(update_payload).eq(
                        "id", first_record["id"]
                    ).execute()

                    # 2. Se ci sono altre proposte identificate nello stesso PDF, inseriamo nuove righe
                    for add_proposal in proposals[1:]:
                        new_row_payload = {
                            "source_file_path": file_path,
                            "proposed_space_name": add_proposal[
                                "proposed_space_name"
                            ],
                            "space_category": add_proposal["space_category"],
                            "spatial_level": add_proposal["spatial_level"],
                            "ai_explanation": add_proposal["ai_explanation"],
                            "confidence": add_proposal["confidence"],
                            "source_page_number": add_proposal[
                                "source_page_number"
                            ],
                            "extracted_text_snippet": add_proposal[
                                "extracted_text_snippet"
                            ],
                            "constructive_elements": add_proposal[
                                "constructive_elements"
                            ],
                            "review_status": "reviewed",
                        }
                        supabase.table(TARGET_TABLE).insert(
                            new_row_payload
                        ).execute()

                    print(
                        f"   [OK] {len(proposals)} distinte proposte create per {file_path}"
                    )
                except Exception as e:
                    print(f"   [ERRORE] {file_path}: {e}")


if __name__ == "__main__":
    process_pending_proposals()
