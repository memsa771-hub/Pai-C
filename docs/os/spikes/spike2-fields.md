# Spike 2 field names per document type

The fields the reader fills and the Spike 2 answer key scores, per document type. The source of truth is
`backend/app/os/documents/types/*.v1.yaml`; this page lists them for the people who verify the answer key.
**No values here:** the real set and its key stay private in `~/spike2-docs` (Slice 3 spec S3-D12).

| Type | Fields (cross-check fields in **bold**) |
|---|---|
| `passport` | surname, given_names (the **full name** is given names + surname), nationality, country_code, **date_of_birth**, sex, place_of_birth, father_or_husband_name, national_id, passport_number, issue_date, expiry_date, tracking_number, booklet_number, mrz_line1, mrz_line2 |
| `degree_certificate` | **student_name**, **father_name**, institution, college, faculty, degree_title, session, exam, completion_date, issue_date, registration_number, roll_number, serial_number, cgpa, cgpa_scale, division |
| `transcript` | **student_name**, **father_name**, **date_of_birth**, national_id, institution, degree_title, student_id, registration_number, enrollment_number, admission_date, completion_date, cgpa, cgpa_scale, percentage, credit_hours, issue_date, serial_number |
| `ssc_certificate`, `hssc_certificate` | **student_name**, **father_name**, **date_of_birth**, board, exam, exam_year, roll_number, registration_number, certificate_number, group, institution, marks_obtained, marks_total, grade, issue_date |
| `ielts_trf` | module, family_name, first_name (the **full name** is first name + family name), **date_of_birth**, sex, nationality, first_language, candidate_id, centre_number, candidate_number, test_date, issue_date, listening, reading, writing, speaking, overall, cefr, trf_number |

Rules between fields:
- passport: the MRZ lines agree with the passport number, date of birth and expiry date, and pass their check digits;
- degree and transcript: CGPA ≤ its scale;
- SSC and HSSC: marks obtained ≤ marks total;
- IELTS: the overall band is the band-rounded mean of the four sections.
