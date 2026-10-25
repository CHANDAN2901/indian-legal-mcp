-- Demo data for supabase-reader-mcp: a small law-practice tracker. Each matter's indiankanoon_case_id is a real
-- case_id from the indiankanoon server, so Claude can join the two. All clients are fictional.
--
-- Load:   paste into the Supabase SQL Editor, or  psql "$SUPABASE_DB_URL" -f demo_seed.sql
-- Remove: DROP TABLE hearings, legal_matters, clients;

BEGIN;

CREATE TABLE clients (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    email text,
    city text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE legal_matters (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id bigint NOT NULL REFERENCES clients,
    title text NOT NULL,
    court text NOT NULL,          -- IndianKanoon doctypes value, e.g. supremecourt, delhi
    status text NOT NULL CHECK (status IN ('open', 'won', 'lost', 'settled')),
    indiankanoon_case_id bigint,  -- leading precedent relied on
    opened_on date NOT NULL,
    notes text
);

CREATE TABLE hearings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    matter_id bigint NOT NULL REFERENCES legal_matters,
    hearing_date date NOT NULL,
    outcome text                  -- null until the hearing has happened
);

-- Keep these tables out of Supabase's public Data API (anon key). The postgres role owns them and still reads them.
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_matters ENABLE ROW LEVEL SECURITY;
ALTER TABLE hearings ENABLE ROW LEVEL SECURITY;

INSERT INTO clients (name, email, city) VALUES
    ('Priya Mehta', 'priya.mehta@example.com', 'Delhi'),
    ('Arjun Rao', 'arjun.rao@example.com', 'Bengaluru'),
    ('Sneha Kulkarni', 'sneha.k@example.com', 'Mumbai'),
    ('Farhan Qureshi', 'farhan.q@example.com', 'Lucknow'),
    ('Meera Iyer', 'meera.iyer@example.com', 'Chennai');

INSERT INTO legal_matters (client_id, title, court, status, indiankanoon_case_id, opened_on, notes) VALUES
    (1, 'Data privacy complaint against telecom operator', 'supremecourt', 'open', 91938676, '2026-03-12',
        'Call records shared with a marketing firm without consent. Relies on privacy as a fundamental right.'),
    (1, 'Defamation suit over magazine article', 'delhi', 'settled', 501107, '2025-07-02',
        'Settled with a published apology.'),
    (2, 'Challenge to bank account freeze', 'karnataka', 'won', 1068532, '2025-01-20',
        'Bank records seized and account frozen without notice.'),
    (3, 'Workplace surveillance of employees', 'bombay', 'open', 91938676, '2026-08-05',
        'Employer installed keystroke logging on personal laptops without consent.'),
    (4, 'Confession under NDPS Act challenged', 'allahabad', 'won', 143202244, '2025-11-18',
        'Prosecution relied on a statement recorded by an NCB officer.'),
    (4, 'Police surveillance and night domiciliary visits', 'lucknow', 'open', 436241, '2026-09-30', NULL),
    (5, 'Dismissal after disclosure of sexual orientation', 'chennai', 'open', 168671544, '2026-06-14',
        'Employer cited conduct rules after the employee came out.'),
    (2, 'Victim participation plea in criminal trial', 'supremecourt', 'lost', 122252422, '2024-10-08', NULL);

INSERT INTO hearings (matter_id, hearing_date, outcome) VALUES
    (1, '2026-04-20', 'Notice issued to respondent'),
    (1, '2026-11-05', NULL),
    (2, '2025-09-15', 'Settlement recorded'),
    (3, '2025-04-02', 'Freeze order quashed'),
    (4, '2026-09-22', 'Interim relief granted'),
    (4, '2026-11-18', NULL),
    (5, '2026-02-10', 'Statement held inadmissible; acquitted'),
    (6, '2026-11-02', NULL),
    (7, '2026-10-30', 'Arguments heard; order reserved'),
    (8, '2025-03-11', 'Petition dismissed');

COMMIT;
