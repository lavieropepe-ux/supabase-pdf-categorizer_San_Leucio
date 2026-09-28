import logging
import os
from io import BytesIO
from pypdf import PdfReader
from supabase import create_client, Client

# Silenzia i warning secondari di pypdf nei log di GitHub Actions
logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError(
        f"ERRORE: Variabili d'ambiente mancanti! "
        f"SUPABASE_URL presente: {bool(SUPABASE_URL)}, "
        f"SUPABASE_SERVICE_ROLE_KEY presente: {bool(SUPABASE_SERVICE_ROLE_KEY)}"
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

BUCKET_NAME = "documents"
TARGET_TABLE = "component_proposals"


def extract_and_analyze_pdf(file_path: str) -> dict:
    """Scarica il PDF, analizza pagina per pagina ed individua la pagina esatta

    in cui viene identificata la parola chiave.
    """
    response = supabase.storage.from_(BUCKET_NAME).download(file_path)
    pdf_file = BytesIO(response)
    reader = PdfReader(pdf_file)

    matched_page = None
    best_analysis = {
        "proposed_space_name": "Complesso Belvedere San Leucio",
        "space_category": "Spazio aperto",
        "spatial_level": "Piano terra",
        "ai_explanation": "Analisi automatica completata (nessuna parola chiave specifica).",
        "confidence": 0.85,
        "source_page_number": None,
    }

    # Scansione pagina per pagina
    for idx, page in enumerate(reader.pages):
        page_num = str(idx + 1)
        page_text = page.extract_text() or ""
        text_lower = page_text.lower()

        if (
            "salone" in text_lower
            or "main hall" in text_lower
            or "rappresentanza" in text_lower
        ):
            return {
                "proposed_space_name": "Belvedere - main hall",
                "space_category": "Cortile principale",
                "spatial_level": "Primo piano",
                "ai_explanation": f"Identificato salone principale del complesso Belvedere a pagina {page_num}.",
                "confidence": 0.95,
                "source_page_number": page_num,
            }

        elif any(
            k in text_lower
            for k in ["setificio", "filanda", "fabbrica", "opificio"]
        ):
            return {
                "proposed_space_name": "New silk factory / Belvedere",
                "space_category": "Cortile principale",
                "spatial_level": "Piano terra",
                "ai_explanation": f"Identificata area produttiva della filanda a pagina {page_num}.",
                "confidence": 0.92,
                "source_page_number": page_num,
            }

        elif any(
            k in text_lower for k in ["residenza", "alloggio", "appartamento"]
        ):
            return {
                "proposed_space_name": "Belvedere residential spaces",
                "space_category": "Spazio aperto",
                "spatial_level": "Primo piano",
                "ai_explanation": f"Rilevati riferimenti agli ambienti residenziali a pagina {page_num}.",
                "confidence": 0.89,
                "source_page_number": page_num,
            }

    return best_analysis


def process_pending_proposals():
    # Elenca i file presenti nello Storage
    files = supabase.storage.from_(BUCKET_NAME).list()

    pdf_files = [f for f in files if f.get("name", "").lower().endswith(".pdf")]

    if not pdf_files:
        print("Nessun file PDF trovato nello Storage.")
        return

    print(f"Trovati {len(pdf_files)} PDF nello Storage da verificare/elaborare.")

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
                print(
                    f"-> Elaborazione del PDF: {file_path} (ID Proposta: {proposal_id})"
                )
                try:
                    analysis = extract_and_analyze_pdf(file_path)

                    # Includiamo 'source_page_number' nel payload di aggiornamento
                    update_payload = {
                        "proposed_space_name": analysis["proposed_space_name"],
                        "space_category": analysis["space_category"],
                        "spatial_level": analysis["spatial_level"],
                        "ai_explanation": analysis["ai_explanation"],
                        "confidence": analysis["confidence"],
                        "source_page_number": analysis["source_page_number"],
                        "review_status": "reviewed",
                    }

                    supabase.table(TARGET_TABLE).update(update_payload).eq(
                        "id", proposal_id
                    ).execute()
                    print(
                        f"   [OK] Aggiornato record e pagina ({analysis['source_page_number']}) per: {file_path}"
                    )
                except Exception as e:
                    print(
                        f"   [ERRORE] Impossibile elaborare il file {file_path}: {e}"
                    )
            else:
                print(
                    f"-> Gia' elaborato (stato '{review_status}'): {file_path}"
                )
        else:
            print(
                f"-> Nessuna riga trovata in '{TARGET_TABLE}' per il file: {file_path}"
            )


if __name__ == "__main__":
    process_pending_proposals()
