import os
from io import BytesIO
from pypdf import PdfReader
from supabase import create_client, Client

# Recupera i segreti d'ambiente
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("ERRORE: Assicurati che SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY siano configurati.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
BUCKET_NAME = "documents"


def list_all_files_in_bucket(path: str = "") -> list:
    """
    Recupera ricorsivamente tutti i file presenti nel bucket 'documents',
    esplorando anche eventuali sotto-cartelle.
    """
    files_list = []
    items = supabase.storage.from_(BUCKET_NAME).list(path)

    for item in items:
        item_name = item.get("name")
        # Se c'est un id/metadata senza nome, salta
        if not item_name:
            continue

        item_path = f"{path}/{item_name}" if path else item_name

        # Verifica se l'elemento è una cartella (id è None nei listing di Supabase)
        if item.get("id") is None:
            files_list.extend(list_all_files_in_bucket(item_path))
        else:
            files_list.append(item_path)

    return files_list


def read_pdf_content(file_path: str) -> str:
    """Scarica un PDF dallo storage e ne estrae il testo completo."""
    response = supabase.storage.from_(BUCKET_NAME).download(file_path)
    pdf_file = BytesIO(response)
    reader = PdfReader(pdf_file)

    full_text = ""
    for page_idx, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            full_text += f"\n--- Pagina {page_idx + 1} ---\n{text}"
    return full_text.strip()


def main():
    print(f"=== Esplorazione bucket '{BUCKET_NAME}' ===")
    all_files = list_all_files_in_bucket()

    if not all_files:
        print("Nessun file trovato nel bucket.")
        return

    print(f"Trovati {len(all_files)} file totali nello Storage.\n")

    pdf_count = 0
    for file_path in all_files:
        if file_path.lower().endswith(".pdf"):
            pdf_count += 1
            print(f"[{pdf_count}] Lettura PDF: {file_path}")
            try:
                content = read_pdf_content(file_path)
                print(f"   -> Caratteri estratti: {len(content)}")
                print(f"   -> Anteprima testo:\n{content[:300]}...\n")
                print("-" * 50)
            except Exception as e:
                print(f"   [ERRORE] Impossibile leggere il PDF {file_path}: {e}\n")
        else:
            print(f"-> Ignorato (non PDF): {file_path}")

    print(f"\nElaborazione completata. Letti {pdf_count} file PDF su {len(all_files)} file totali.")


if __name__ == "__main__":
    main()
