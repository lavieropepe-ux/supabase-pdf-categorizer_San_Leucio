import logging
import os
from io import BytesIO
from pypdf import PdfReader
from supabase import create_client, Client

# Silenzia i warning secondari di pypdf nei log di GitHub Actions
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Recupera i segreti d'ambiente
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


def get_pdf_text_from_storage(file_path: str) -> str:
    """Scarica il PDF dal bucket 'documents' in memoria ed estrae il testo."""
    response = supabase.storage.from_(BUCKET_NAME).download(file_path)
    pdf_file = BytesIO(response)
    reader = PdfReader(pdf_file)

    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


def analyze_and_categorize(text: str) -> dict:
    """Analizza il testo del documento inerente al complesso di San Leucio
    e determina le informazioni spaziali ed edilizie.
    """
    text_lower = text.lower()

    proposed_space_name = "Complesso Belvedere San Leucio"
    space_category = "Spazio aperto"
    spatial_level = "Piano terra"
    ai_explanation = "Analisi automatica completata."
    confidence = 0.85

    if (
        "salone" in text_lower
        or "main hall" in text_lower
        or "rappresentanza" in text_lower
    ):
        proposed_space_name = "Belvedere - main hall"
        space_category = "Cortile principale"
        spatial_level = "Primo piano"
        ai_explanation = "Identificato salone principale del complesso Belvedere dalle fonti documentali."
        confidence = 0.95
    elif (
        "setificio" in text_lower
        or "filanda" in text_lower
        or "fabbrica" in text_lower
        or "opificio" in text_lower
    ):
        proposed_space_name = "New silk factory / Belvedere"
        space_category = "Cortile principale"
        spatial_level = "Piano terra"
        ai_explanation = "Identificata area produttiva o manifatturiera della filanda di San Leucio."
        confidence = 0.92
    elif (
        "residenza" in text_lower
        or "alloggio" in text_lower
        or "appartamento" in text_lower
    ):
        proposed_space_name = "Belvedere residential spaces"
        space_category = "Spazio aperto"
        spatial_level = "Primo piano"
        ai_explanation = (
            "Rilevati riferimenti agli ambienti residenziali del quartiere borbonico."
        )
        confidence = 0.89
    elif (
        "esterno" in text_lower
        or "edifici" in text_lower
        or "prospetto" in text_lower
    ):
        proposed_space_name = "Belvedere and surrounding buildings"
        space_category = "Spazio aperto"
        spatial_level = "Piano terra"
        ai_explanation = (
            "Identificati riferimenti al contesto urbano ed edifici circostanti."
        )
        confidence = 0.90

    return {
        "proposed_space_name": proposed_space_name,
        "space_category": space_category,
        "spatial_level": spatial_level,
        "ai_explanation": ai_explanation,
        "confidence": confidence,
    }


def process_pending_proposals():
    # Elenca i file presenti direttamente nel bucket dello Storage
    files = supabase.storage.from_(BUCKET_NAME).list()

    pdf_files = [f for f in files if f.get("name", "").lower().endswith(".pdf")]

    if not pdf_files:
        print("Nessun file PDF trovato nello Storage.")
        return

    print(f"Trovati {len(pdf_files)} PDF nello Storage da verificare/elaborare.")

    for file_info in pdf_files:
        file_path = file_info["name"]

        # Cerca il record corrispondente nella tabella component_proposals
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
                    pdf_text = get_pdf_text_from_storage(file_path)
                    analysis = analyze_and_categorize(pdf_text)

                    update_payload = {
                        "proposed_space_name": analysis["proposed_space_name"],
                        "space_category": analysis["space_category"],
                        "spatial_level": analysis["spatial_level"],
                        "ai_explanation": analysis["ai_explanation"],
                        "confidence": analysis["confidence"],
                        "review_status": "reviewed",
                    }

                    supabase.table(TARGET_TABLE).update(update_payload).eq(
                        "id", proposal_id
                    ).execute()
                    print(f"   [OK] Aggiornato record per: {file_path}")
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
