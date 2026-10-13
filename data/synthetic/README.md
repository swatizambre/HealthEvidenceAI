# Synthetic data

Patient facts come from the public Synthea sample published by MITRE:

https://synthetichealth.github.io/synthea-sample-data/downloads/latest/synthea_sample_data_csv_latest.zip

Synthea generates synthetic patients. They are not real people. Cite Synthea as Walonoski et al., JAMIA, 2018, https://doi.org/10.1093/jamia/ocx079.

The seed keeps 100 patients from that file. It copies conditions, medications, laboratory observations, procedures, imaging metadata, and claim status. It does not copy names, addresses, phone numbers, SSNs, passport numbers, or driver license numbers. Display names in this app are `Synthetic Patient 000001`.

The CSV archive is downloaded into `data/synthetic/cache/` and is not committed. Do not replace it with real patient data.
