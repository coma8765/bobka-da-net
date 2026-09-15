-- Иерархия складских секций по уровням
WITH RECURSIVE section_tree AS (
    SELECT
        ws.section_id,
        ws.warehouse_id,
        ws.parent_section_id,
        ws.code,
        ws.name,
        0 AS depth,
        ARRAY[ws.section_id] AS path
    FROM warehouse_sections AS ws
    WHERE ws.parent_section_id IS NULL
      AND ws.warehouse_id = (
          SELECT MIN(warehouse_id)
          FROM warehouse_sections
          WHERE parent_section_id IS NOT NULL
      )

    UNION ALL

    SELECT
        child.section_id,
        child.warehouse_id,
        child.parent_section_id,
        child.code,
        child.name,
        parent.depth + 1,
        parent.path || child.section_id
    FROM warehouse_sections AS child
    JOIN section_tree AS parent
      ON child.warehouse_id = parent.warehouse_id
     AND child.parent_section_id = parent.section_id
    WHERE NOT child.section_id = ANY(parent.path)
)
SELECT section_id, parent_section_id, code, name, depth
FROM section_tree
ORDER BY path;
