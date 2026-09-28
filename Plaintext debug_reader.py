import logging
import os
from io import BytesIO
from pypdf import PdfReader
from supabase import create_client, Client

# Silenzia i warning secondari
logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("Variabili SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY mancanti.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
BUCKET_NAME = "documents"

def debug_pdf_extraction():
    # Recupera i file e le pagine specificate nel DB
    response = supabase.table("component_proposals").select("source_file_path, source_page_number").execute()
    
    for record in response.data:
        file_path = record.get("source_file_path")
        pages_str = record.get("source_page_number")

        if not file_path or not file_path.lower().endswith(".pdf"):
            continue

        print("\n" + "="*80)
        print(f"FILE: {file_path}")
        print(f"PAGINE INDICATE NEL DB: {pages_str}")
        print("="*80)

        try:
            # Download del PDF da Supabase Storage
            response_file = supabase.storage.from_(BUCKET_NAME).download(file_path)
            pdf_file = BytesIO(response_file)
            reader = PdfReader(pdf_file)
            total_pages = len(reader.pages)

            print(f"Totale pagine nel PDF: {total_pages}\n")

            # Estrae e stampa il testo
            for idx, page in enumerate(reader.pages):
                page_num = idx + 1
                text = page.extract_text() or ""
                
                # Stampa un'anteprima delle prime 300 lettere di ciascuna pagina
                print(f"--- [PAGINA {page_num}] (Lunghezza testo: {len(text)} caratteri) ---")
                if text.strip():
                    print(text[:300].replace("\n", " ") + "...\n")
                else:
                    print("[NESSUN TESTO ESTRATTO - Pagina vuota o scansione immagine]\n")

        except Exception as e:
            print(f"[ERRORE durante la lettura del file {file_path}]: {e}")

if __name__ == "__main__":
    debug_pdf_extraction()
