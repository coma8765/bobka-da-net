"""NiFi ExecuteStreamCommand: validate stdin without rewriting the original bytes."""

import sys

from validation import MAX_BYTES, decode_json, validate_records


def main():
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    try:
        if len(sys.argv) != 2:
            raise ValueError("expected source filename")
        validate_records(decode_json(raw), sys.argv[1])
    except (ValueError, TypeError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
