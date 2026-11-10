-- RAW layer: load openFDA JSON exactly as received (only the columns the analysis needs).
-- Paths are relative to the project root; src/build.py runs from there.
-- Empty windows are valid gz files with no rows.

CREATE OR REPLACE TABLE raw_event AS
SELECT *
FROM read_json(
    'data/raw/event/*/*.jsonl.gz',
    format = 'newline_delimited',
    compression = 'gzip',
    maximum_object_size = 33554432,
    filename = true,
    columns = {
        report_number: 'VARCHAR',
        mdr_report_key: 'VARCHAR',
        event_key: 'VARCHAR',
        date_received: 'VARCHAR',
        date_of_event: 'VARCHAR',
        event_type: 'VARCHAR',
        type_of_report: 'VARCHAR[]',
        mfr_report_type: 'VARCHAR',
        summary_report_flag: 'VARCHAR',
        report_source_code: 'VARCHAR',
        manufacturer_name: 'VARCHAR',
        product_problems: 'VARCHAR[]',
        device: 'STRUCT(brand_name VARCHAR, generic_name VARCHAR, manufacturer_d_name VARCHAR, model_number VARCHAR, device_report_product_code VARCHAR)[]'
    }
);

CREATE OR REPLACE TABLE raw_recall AS
SELECT *
FROM read_json(
    'data/raw/recall/*.jsonl.gz',
    format = 'newline_delimited',
    compression = 'gzip',
    maximum_object_size = 33554432,
    columns = {
        product_res_number: 'VARCHAR',
        res_event_number: 'VARCHAR',
        product_code: 'VARCHAR',
        recalling_firm: 'VARCHAR',
        event_date_initiated: 'VARCHAR',
        event_date_posted: 'VARCHAR',
        recall_status: 'VARCHAR',
        root_cause_description: 'VARCHAR',
        reason_for_recall: 'VARCHAR',
        product_description: 'VARCHAR'
    }
);

CREATE OR REPLACE TABLE raw_classification AS
SELECT *
FROM read_json(
    'data/raw/classification.jsonl.gz',
    format = 'newline_delimited',
    compression = 'gzip',
    columns = {
        product_code: 'VARCHAR',
        device_name: 'VARCHAR',
        device_class: 'VARCHAR',
        medical_specialty_description: 'VARCHAR'
    }
);
