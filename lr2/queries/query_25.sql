-- Уникальные строки после удаления дублей
WITH duplicated_rows AS (
    SELECT
        p.product_id,
        p.name,
        p.category,
        duplicate_number
    FROM products AS p
    -- создание дублей каждого товара
    CROSS JOIN generate_series(1, 2) AS duplicate_number
    WHERE p.product_id <= 10
),
numbered_rows AS (
    SELECT
        product_id,
        name,
        category,
        -- присваиваем номер строки каждому из строк результата подзапроса
        ROW_NUMBER() OVER (
            PARTITION BY product_id, name, category
            ORDER BY duplicate_number
        ) AS row_number
    FROM duplicated_rows
)
SELECT product_id, name, category
FROM numbered_rows
WHERE row_number = 1
ORDER BY product_id;
