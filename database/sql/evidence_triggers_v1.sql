-- Evidence integrity, enforced in the database (PRD §8.2), version 1.

-- 1. extracted_text must be the verbatim span [char_start, char_end) of the document text;
--    the document text must belong to the raw document; the company must match the document's
--    company (market-wide documents have no company); public_at must equal the document's.
CREATE OR REPLACE FUNCTION sa_evidence_check_span() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    doc_text text;
    doc_id bigint;
    doc_company bigint;
    doc_public timestamptz;
BEGIN
    SELECT dt.text, dt.raw_document_id INTO doc_text, doc_id
    FROM document_texts dt WHERE dt.id = NEW.document_text_id;
    IF doc_id IS NULL THEN
        RAISE EXCEPTION 'evidence: unknown document_text %', NEW.document_text_id;
    END IF;
    IF doc_id <> NEW.raw_document_id THEN
        RAISE EXCEPTION 'evidence: document_text % does not belong to raw_document %',
            NEW.document_text_id, NEW.raw_document_id;
    END IF;
    IF NEW.char_start < 0 OR NEW.char_end <= NEW.char_start OR NEW.char_end > length(doc_text) THEN
        RAISE EXCEPTION 'evidence: span [%, %) is outside the document', NEW.char_start, NEW.char_end;
    END IF;
    IF substr(doc_text, NEW.char_start + 1, NEW.char_end - NEW.char_start) <> NEW.extracted_text THEN
        RAISE EXCEPTION 'evidence: extracted_text is not the verbatim span of the document';
    END IF;
    SELECT company_id, public_at INTO doc_company, doc_public
    FROM raw_documents WHERE id = NEW.raw_document_id;
    IF doc_company IS NOT NULL AND doc_company <> NEW.company_id THEN
        RAISE EXCEPTION 'evidence: company % does not own document %', NEW.company_id, NEW.raw_document_id;
    END IF;
    IF NEW.public_at <> doc_public THEN
        RAISE EXCEPTION 'evidence: public_at must equal the document public_at';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_evidence_check_span
    BEFORE INSERT ON evidence
    FOR EACH ROW EXECUTE FUNCTION sa_evidence_check_span();

-- 2. Evidence is immutable: corrections create new records. (Deletion is reserved for
--    dataset resets such as regenerating mock data and is not blocked.)
CREATE OR REPLACE FUNCTION sa_evidence_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'evidence records are immutable; create a new record instead';
END $$;

CREATE TRIGGER trg_evidence_immutable
    BEFORE UPDATE ON evidence
    FOR EACH ROW EXECUTE FUNCTION sa_evidence_immutable();
