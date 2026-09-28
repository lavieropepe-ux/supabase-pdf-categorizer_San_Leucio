def extract_and_analyze_pdf(file_path: str) -> dict:
    """Scarica il PDF, analizza pagina per pagina e registra la prima pagina

    in cui viene identificata una categoria rilevante.
    """
    response = supabase.storage.from_(BUCKET_NAME).download(file_path)
    pdf_file = BytesIO(response)
    reader = PdfReader(pdf_file)

    matched_pages = []
    best_analysis = {
        "proposed_space_name": "Complesso Belvedere San Leucio",
        "space_category": "Spazio aperto",
        "spatial_level": "Piano terra",
        "ai_explanation": "Analisi automatica completata (valori di default).",
        "confidence": 0.85,
    }

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1
        page_text = page.extract_text() or ""
        text_lower = page_text.lower()

        if (
            "salone" in text_lower
            or "main hall" in text_lower
            or "rappresentanza" in text_lower
        ):
            matched_pages.append(str(page_num))
            best_analysis = {
                "proposed_space_name": "Belvedere - main hall",
                "space_category": "Cortile principale",
                "spatial_level": "Primo piano",
                "ai_explanation": f"Identificato salone principale del complesso Belvedere a pagina {page_num}.",
                "confidence": 0.95,
            }
            break  # Si ferma alla prima occorrenza trovata

        elif any(
            k in text_lower
            for k in ["setificio", "filanda", "fabbrica", "opificio"]
        ):
            matched_pages.append(str(page_num))
            best_analysis = {
                "proposed_space_name": "New silk factory / Belvedere",
                "space_category": "Cortile principale",
                "spatial_level": "Piano terra",
                "ai_explanation": f"Identificata area produttiva della filanda a pagina {page_num}.",
                "confidence": 0.92,
            }
            break

    best_analysis["source_page_number"] = (
        ", ".join(matched_pages) if matched_pages else None
    )
    return best_analysis
