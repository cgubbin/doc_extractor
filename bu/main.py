if __name__ == "__main__":
    from config import PipelineConfig
    from runner import process_patent_pdf

    cfg = PipelineConfig(
        figure_mode="auto",
        pdftotext_layout=True,
        pdftotext_raw=True,
    )

    submitted = process_patent_pdf(
        pdf_path="./submitted.pdf",
        out_dir="runs",
        doc_id="example_submitted",
        cfg=cfg,
    )

    print(f"Processed submitted patent: {submitted}")
