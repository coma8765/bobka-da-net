#!/bin/bash

  podman exec lr1-postgres psql -U postgres -d supply_lab \
    -c "SELECT * FROM suppliers ORDER BY supplier_id DESC LIMIT 5;"

  podman exec lr1-postgres psql -U postgres -d supply_lab \
    -c "SELECT * FROM products ORDER BY product_id DESC LIMIT 5;"

  podman exec lr1-postgres psql -U postgres -d supply_lab \
    -c "SELECT * FROM warehouses ORDER BY warehouse_id DESC LIMIT 5;"

  podman exec lr1-postgres psql -U postgres -d supply_lab \
    -c "SELECT * FROM warehouse_sections ORDER BY section_id DESC LIMIT 5;"

  podman exec lr1-postgres psql -U postgres -d supply_lab \
    -c "SELECT * FROM deliveries ORDER BY delivery_id DESC LIMIT 5;"
