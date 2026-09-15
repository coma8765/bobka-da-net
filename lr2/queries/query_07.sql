-- Средняя стоимость поставки двумя способами
SELECT
    ROUND(AVG(unit_cost * quantity), 2) AS actual_average,
    ROUND(SUM(unit_cost * quantity) / NULLIF(COUNT(*), 0), 2) AS calculated_average
FROM deliveries;
