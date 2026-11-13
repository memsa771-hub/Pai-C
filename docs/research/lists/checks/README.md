# Checks of list entries

`2026-11-13-unlisted-sources-check{1,2}.yaml`: the eight source URLs cited by batch institution rows that had no
official-list entry (the import rejected 95 rows with `no_official_list`). Check 1 decided per URL whether it is an
official list, counted its institutions and found each cited row on it; check 2 did the same independently, from its
own downloads, without seeing check 1. Both are AI checks (owner ruling, P2 spec §11.2). They agree on every decision,
every row count (71, 75, 9, 4, 3) and every cited row. The printed notification dates of the two UHS prospectuses
(check 2) were used over the PDF metadata dates (check 1).

Five became list entries (punjab.yaml, sindh.yaml, balochistan.yaml, ict.yaml). Three are not lists: `cas.kmu.edu.pk`
(an admission portal), `imcgf72.edu.pk/Admissin_Policy.aspx` (one college's policy page) and
`dapr.kiu.edu.pk/...` (a university's admission rules); the rows citing them stay rejected until they point at the list
that names them (HEC's recognised-universities list for KMU and KIU, the FDE institutions page for the Islamabad model
college).

Lines read from images (the private-college tables of both UHS prospectuses, and the SZABMU notice) were read by a
model; a person should confirm them (R-72). The downloaded documents are not kept in the repo.
