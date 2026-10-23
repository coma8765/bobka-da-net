"""Build the reproducible, secret-free NiFi 2.6.0 process group snapshot."""

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from validation import FILENAME  # noqa: E402

VERSION = "2.6.0"
NAMESPACE = uuid.UUID("ef939279-0334-43e1-ac87-828672bb26cb")


def identifier(name):
    return str(uuid.uuid5(NAMESPACE, name))


def build():
    group_id = identifier("group")
    processors, services, connections = [], [], []

    def service(name, cls, artifact, props):
        obj = dict(
            identifier=identifier(name),
            name=name,
            type=cls,
            bundle=dict(group="org.apache.nifi", artifact=artifact, version=VERSION),
            properties=props,
            propertyDescriptors={},
            controllerServiceApis=[],
            annotationData=None,
            comments="",
            componentType="CONTROLLER_SERVICE",
            groupIdentifier=group_id,
        )
        services.append(obj)
        return obj["identifier"]

    schema = json.dumps(json.loads((ROOT / "nifi/delivery-event.avsc").read_text()))
    reader = service(
        "JSON reader",
        "org.apache.nifi.json.JsonTreeReader",
        "nifi-record-serialization-services-nar",
        {
            "schema-access-strategy": "schema-text-property",
            "schema-text": schema,
            "Timestamp Format": "yyyy-MM-dd'T'HH:mm:ss'Z'",
            "Date Format": "yyyy-MM-dd",
        },
    )
    writer = service(
        "JSON writer",
        "org.apache.nifi.json.JsonRecordSetWriter",
        "nifi-record-serialization-services-nar",
        {
            "schema-access-strategy": "inherit-record-schema",
            "Schema Write Strategy": "no-schema",
            "output-grouping": "output-array",
            "Pretty Print JSON": "false",
            "Timestamp Format": "yyyy-MM-dd'T'HH:mm:ss'Z'",
            "Date Format": "yyyy-MM-dd",
        },
    )
    db = service(
        "PostgreSQL supply_lab",
        "org.apache.nifi.dbcp.DBCPConnectionPool",
        "nifi-dbcp-service-nar",
        {
            "Database Connection URL": "#{jdbc.url}",
            "Database Driver Class Name": "org.postgresql.Driver",
            "database-driver-locations": "/opt/nifi/jdbc/postgresql.jar",
            "Database User": "#{jdbc.user}",
            "Password": "#{jdbc.password}",
            "Validation-query": "SELECT 1",
        },
    )

    def proc(
        name,
        kind,
        props=None,
        terminate=(),
        period="0 sec",
        artifact="nifi-standard-nar",
    ):
        cls = "org.apache.nifi.processors.standard." + kind
        if kind == "UpdateAttribute":
            cls = "org.apache.nifi.processors.attributes.UpdateAttribute"
            artifact = "nifi-update-attribute-nar"
        obj = dict(
            identifier=identifier(name),
            name=name,
            type=cls,
            bundle=dict(group="org.apache.nifi", artifact=artifact, version=VERSION),
            properties=props or {},
            propertyDescriptors={},
            position=dict(
                x=(len(processors) % 4) * 420, y=(len(processors) // 4) * 220
            ),
            style={},
            schedulingPeriod=period,
            schedulingStrategy="TIMER_DRIVEN",
            executionNode="ALL",
            concurrentlySchedulableTaskCount=1,
            penaltyDuration="30 sec",
            yieldDuration="1 sec",
            runDurationMillis=0,
            bulletinLevel="WARN",
            autoTerminatedRelationships=list(terminate),
            scheduledState="ENABLED",
            retryCount=10,
            retriedRelationships=[],
            backoffMechanism="PENALIZE_FLOWFILE",
            maxBackoffPeriod="10 mins",
            componentType="PROCESSOR",
            groupIdentifier=group_id,
            comments="",
        )
        processors.append(obj)
        return name

    def link(source, rel, target):
        connections.append(
            dict(
                identifier=identifier(f"{source}/{rel}/{target}"),
                name="",
                source=dict(
                    id=identifier(source),
                    type="PROCESSOR",
                    groupId=group_id,
                    name=source,
                ),
                destination=dict(
                    id=identifier(target),
                    type="PROCESSOR",
                    groupId=group_id,
                    name=target,
                ),
                selectedRelationships=[rel],
                backPressureObjectThreshold=100,
                backPressureDataSizeThreshold="16 MB",
                flowFileExpiration="0 sec",
                prioritizers=[],
                bends=[],
                labelIndex=0,
                zIndex=0,
                loadBalanceStrategy="DO_NOT_LOAD_BALANCE",
                loadBalanceCompression="DO_NOT_COMPRESS",
                componentType="CONNECTION",
                groupIdentifier=group_id,
            )
        )

    proc(
        "Read inbox",
        "GetFile",
        {
            "Input Directory": "/opt/nifi/lr8/runtime/inbox",
            "File Filter": r".*\.json",
            "Keep Source File": "false",
            "Recurse Subdirectories": "false",
            "Batch Size": "20",
        },
        period="10 sec",
    )
    proc(
        "Remember source",
        "UpdateAttribute",
        {
            "source.filename": "${filename}",
            "source.uuid": "${uuid}",
            "load.status": "processing",
            "record_count": "0",
            "file_id": '${filename:substringBefore("__")}',
            "table_name": "delivery_events",
            "formed_at": '${filename:substringAfterLast("__"):substringBeforeLast(".")}',
            "error.stage": "filename",
            "error.reason": "invalid filename or file larger than 1 MiB",
        },
    )
    proc(
        "Check filename and size",
        "RouteOnAttribute",
        {
            "valid": '${filename:matches("^'
            + FILENAME.pattern.replace("(?P<file_id>", "(?:")
            .replace("(?P<formed_at>", "(?:")
            .replace(r"\.", "[.]")
            + '$"):and(${fileSize:le(1048576)})}',
        },
    )
    proc(
        "Remember original bytes",
        "ExtractText",
        {
            "original.content": r"(?s)\A(.*)\z",
            "Maximum Buffer Size": "1 MB",
            "Maximum Capture Group Length": "1048576",
            "Include Capture Group 0": "false",
        },
    )
    proc(
        "Validate complete file",
        "ExecuteStreamCommand",
        {
            "Command Path": "/usr/bin/python3",
            "Command Arguments": "/opt/nifi/lr8/src/validate_file.py;${source.filename}",
            "Argument Delimiter": ";",
            "Ignore STDIN": "false",
        },
        terminate=("output stream", "nonzero status"),
    )
    proc(
        "Check validation result",
        "RouteOnAttribute",
        {"valid": '${execution.status:equals("0")}'},
    )
    proc(
        "Validation error",
        "UpdateAttribute",
        {
            "error.stage": "whole_file_validation",
            "error.reason": "${execution.error}",
        },
    )
    proc(
        "Validate record schema",
        "ValidateRecord",
        {
            "record-reader": reader,
            "record-writer": writer,
            "schema-access-strategy": "schema-text-property",
            "schema-text": schema,
            "allow-extra-fields": "false",
            "strict-type-checking": "true",
            "coerce-types": "true",
            "validation-details-attribute-name": "validation.details",
        },
    )
    proc(
        "Convert to JSON",
        "ConvertRecord",
        {"record-reader": reader, "record-writer": writer},
    )
    proc(
        "Remember record count", "UpdateAttribute", {"record_count": "${record.count}"}
    )
    proc(
        "Split array",
        "SplitJson",
        {"JsonPath Expression": "$[*]"},
        terminate=("original",),
    )
    proc(
        "Reassemble file",
        "MergeContent",
        {
            "Merge Strategy": "Defragment",
            "Merge Format": "Binary Concatenation",
            "Delimiter Strategy": "Text",
            "Header File": "[",
            "Footer File": "]",
            "Demarcator File": ",",
            "Attribute Strategy": "Keep Only Common Attributes",
            "Max Bin Age": "1 min",
            "Maximum Number of Entries": "20",
        },
        terminate=("original",),
    )
    proc("Restore filename", "UpdateAttribute", {"filename": "${source.filename}"})
    proc(
        "Insert whole file",
        "PutDatabaseRecord",
        {
            "put-db-record-record-reader": reader,
            "put-db-record-dcbp-service": db,
            "db-type": "PostgreSQL",
            "put-db-record-statement-type": "INSERT",
            "put-db-record-schema-name": "lr8",
            "put-db-record-table-name": "delivery_events",
            "put-db-record-translate-field-names": "false",
            "put-db-record-unmatched-field-behavior": "Fail on Unmatched Fields",
            "put-db-record-unmatched-column-behavior": "Ignore Unmatched Columns",
            "database-session-autocommit": "false",
        },
    )
    proc(
        "Classify database failure",
        "RouteOnAttribute",
        {
            "permanent": "${putdatabaserecord.error:matches('(?is).*(duplicate key value violates unique constraint|violates check constraint|violates not-null constraint|value too long for type|invalid input syntax for type|numeric field overflow).*')}"
        },
    )
    proc(
        "Retry database",
        "RetryFlowFile",
        {
            "retry-attribute": "database.retries",
            "maximum-retries": "10",
            "penalize-retries": "true",
            "reuse-mode": "reset",
        },
    )
    proc("Reset database retry", "UpdateAttribute", {"database.retries": "0"})
    proc(
        "Database error",
        "UpdateAttribute",
        {
            "error.stage": "database",
            "error.reason": "${putdatabaserecord.error:replaceAll('(?s)^.*ERROR: ', 'ERROR: ')}",
        },
    )
    proc(
        "Transformation error",
        "UpdateAttribute",
        {
            "error.stage": "transform",
            "error.reason": "record conversion or defragmentation failed; inspect provenance",
        },
    )
    proc(
        "Restore rejected original",
        "ReplaceText",
        {
            "Replacement Strategy": "Always Replace",
            "Evaluation Mode": "Entire text",
            "Replacement Value": "${original.content}",
            "Maximum Buffer Size": "1 MB",
        },
    )
    proc(
        "Mark rejected",
        "UpdateAttribute",
        {
            "load.status": "rejected",
            "processed_at": "${now():format(\"yyyy-MM-dd'T'HH:mm:ss'Z'\", 'UTC')}",
            "filename": "${source.filename}.${source.uuid}.rejected.json",
        },
    )
    proc(
        "Save rejected",
        "PutFile",
        {
            "Directory": "/opt/nifi/lr8/runtime/rejected",
            "Conflict Resolution Strategy": "replace",
            "Create Missing Directories": "true",
        },
    )
    proc(
        "Rejected receipt name",
        "UpdateAttribute",
        {"filename": "${filename}.error.json"},
    )
    proc(
        "Restore archived original",
        "ReplaceText",
        {
            "Replacement Strategy": "Always Replace",
            "Evaluation Mode": "Entire text",
            "Replacement Value": "${original.content}",
            "Maximum Buffer Size": "1 MB",
        },
    )
    proc(
        "Mark committed",
        "UpdateAttribute",
        {
            "load.status": "committed",
            "committed_at": "${now():format(\"yyyy-MM-dd'T'HH:mm:ss'Z'\", 'UTC')}",
            "archive.date": "${now():format('yyyy-MM-dd', 'UTC')}",
            "filename": "${source.filename}",
        },
    )
    proc(
        "Archive source",
        "PutFile",
        {
            "Directory": "/opt/nifi/lr8/runtime/archive/${archive.date}",
            "Conflict Resolution Strategy": "replace",
            "Create Missing Directories": "true",
        },
    )
    proc(
        "Loaded receipt name",
        "UpdateAttribute",
        {
            "filename": "${source.filename}.loaded.json",
            "load.status": "loaded",
            "processed_at": "${now():format(\"yyyy-MM-dd'T'HH:mm:ss'Z'\", 'UTC')}",
            "Delete Attributes Expression": "error\\..*",
        },
    )
    attrs = "source.uuid,source.filename,file_id,table_name,formed_at,record_count,fragment.identifier,load.status,processed_at,committed_at,error.stage,error.reason"
    for name in ("Loaded receipt", "Rejected receipt"):
        proc(
            name,
            "AttributesToJSON",
            {
                "Attributes List": attrs,
                "Destination": "flowfile-content",
                "Include Core Attributes": "false",
            },
        )
    proc(
        "Save loaded receipt",
        "PutFile",
        {
            "Directory": "/opt/nifi/lr8/runtime/receipts",
            "Conflict Resolution Strategy": "replace",
            "Create Missing Directories": "true",
        },
    )
    proc(
        "Save rejected receipt",
        "PutFile",
        {
            "Directory": "/opt/nifi/lr8/runtime/rejected",
            "Conflict Resolution Strategy": "replace",
            "Create Missing Directories": "true",
        },
    )
    for name, level in (("Log loaded", "info"), ("Log rejected", "warn")):
        proc(
            name,
            "LogAttribute",
            {"Log Level": level, "Log Payload": "false", "Attributes to Log": attrs},
            terminate=("success",),
        )

    for source, rel, target in [
        ("Read inbox", "success", "Remember source"),
        ("Remember source", "success", "Check filename and size"),
        ("Check filename and size", "valid", "Remember original bytes"),
        ("Check filename and size", "unmatched", "Mark rejected"),
        ("Remember original bytes", "matched", "Validate complete file"),
        ("Remember original bytes", "unmatched", "Mark rejected"),
        ("Validate complete file", "original", "Check validation result"),
        ("Check validation result", "valid", "Validate record schema"),
        ("Check validation result", "unmatched", "Validation error"),
        ("Validation error", "success", "Mark rejected"),
        ("Validate record schema", "valid", "Convert to JSON"),
        ("Convert to JSON", "success", "Remember record count"),
        ("Remember record count", "success", "Split array"),
        ("Split array", "split", "Reassemble file"),
        ("Reassemble file", "merged", "Restore filename"),
        ("Restore filename", "success", "Insert whole file"),
        ("Insert whole file", "success", "Mark committed"),
        ("Insert whole file", "retry", "Retry database"),
        ("Insert whole file", "failure", "Classify database failure"),
        ("Classify database failure", "permanent", "Database error"),
        ("Classify database failure", "unmatched", "Retry database"),
        ("Retry database", "retry", "Insert whole file"),
        ("Retry database", "retries_exceeded", "Reset database retry"),
        ("Retry database", "failure", "Reset database retry"),
        ("Reset database retry", "success", "Retry database"),
        ("Database error", "success", "Restore rejected original"),
        ("Transformation error", "success", "Restore rejected original"),
        ("Restore rejected original", "success", "Mark rejected"),
        ("Restore rejected original", "failure", "Restore rejected original"),
        ("Mark rejected", "success", "Save rejected"),
        ("Save rejected", "success", "Rejected receipt name"),
        ("Rejected receipt name", "success", "Rejected receipt"),
        ("Rejected receipt", "success", "Save rejected receipt"),
        ("Save rejected receipt", "success", "Log rejected"),
        ("Mark committed", "success", "Restore archived original"),
        ("Restore archived original", "success", "Archive source"),
        ("Restore archived original", "failure", "Restore archived original"),
        ("Archive source", "success", "Loaded receipt name"),
        ("Loaded receipt name", "success", "Loaded receipt"),
        ("Loaded receipt", "success", "Save loaded receipt"),
        ("Save loaded receipt", "success", "Log loaded"),
    ]:
        link(source, rel, target)
    for name in (
        "Validate record schema",
        "Convert to JSON",
        "Split array",
        "Reassemble file",
    ):
        link(name, "failure", "Transformation error")
    link("Validate record schema", "invalid", "Transformation error")
    for name in (
        "Save rejected",
        "Save rejected receipt",
        "Archive source",
        "Save loaded receipt",
    ):
        link(name, "failure", name)
    for name in ("Loaded receipt", "Rejected receipt"):
        link(name, "failure", name)
    # Explicit descriptors are needed to remap controller-service references on import.
    for processor in processors:
        for key in (
            "record-reader",
            "record-writer",
            "put-db-record-dcbp-service",
            "put-db-record-record-reader",
        ):
            if key in processor["properties"]:
                processor["propertyDescriptors"][key] = {
                    "name": key,
                    "displayName": key,
                    "identifiesControllerService": True,
                    "sensitive": False,
                }
    group = dict(
        identifier=group_id,
        name="lr8-delivery-import",
        comments="Whole-file validation, transactional INSERT, durable archive and receipts.",
        position=dict(x=0, y=0),
        processGroups=[],
        remoteProcessGroups=[],
        processors=processors,
        controllerServices=services,
        connections=connections,
        inputPorts=[],
        outputPorts=[],
        funnels=[],
        labels=[],
        parameterContextName="lr8",
        defaultFlowFileExpiration="0 sec",
        defaultBackPressureObjectThreshold=100,
        defaultBackPressureDataSizeThreshold="16 MB",
        flowFileConcurrency="UNBOUNDED",
        flowFileOutboundPolicy="STREAM_WHEN_AVAILABLE",
        componentType="PROCESS_GROUP",
    )
    params = [
        dict(
            name="jdbc.url",
            description="PostgreSQL URL",
            sensitive=False,
            value="jdbc:postgresql://host.containers.internal:55432/supply_lab?stringtype=unspecified&logServerErrorDetail=false",
        ),
        dict(
            name="jdbc.user",
            description="Database user",
            sensitive=False,
            value="postgres",
        ),
        dict(name="jdbc.password", description="Set after import", sensitive=True),
    ]
    return dict(
        flowContents=group,
        externalControllerServices={},
        parameterContexts={
            "lr8": dict(name="lr8", parameters=params, inheritedParameterContexts=[])
        },
        flowEncodingVersion="1.0",
        parameterProviders={},
        latest=True,
    )


if __name__ == "__main__":
    destination = ROOT / "nifi/lr8-delivery-import.json"
    destination.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n")
