import os
from io import BytesIO
from pypdf import PdfReader
from supabase import create_client, Client

# Recupera i segreti impostati su GitHub Actions
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Controllo di sicurezza sulle variabili d'ambiente
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
    # Recupera le proposte create dal trigger in stato 'to_review'
    response = (
        supabase.table(TARGET_TABLE)
        .select("id, source_file_path")
        .eq("review_status", "to_review")
        .execute()
    )
    pending_records = response.data

    if not pending_records:
        print(
            "Nessun documento in attesa di elaborazione (review_status = 'to_review')."
        )
        return

    print(f"Trovate {len(pending_records)} proposte da elaborare.")

    for record in pending_records:
        proposal_id = record["id"]
        file_path = record["source_file_path"]

        print(
            f"-> Elaborazione del file: {file_path} (ID Proposta: {proposal_id})"
        )

        try:
            # Estrazione e categorizzazione del testo
            pdf_text = get_pdf_text_from_storage(file_path)
            analysis = analyze_and_categorize(pdf_text)

            # Aggiornamento del record esistente nella tabella
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
            print(
                f"   [OK] Aggiornata proposta {proposal_id} per il file: {file_path}"
            )

        except Exception as e:
            print(f"   [ERRORE] Impossibile elaborare il file {file_path}: {e}")


if __name__ == "__main__":
    process_pending_proposals()
