-- Поставки с расшифровкой статуса качества
SELECT
    delivery_id,
    batch_number,
    CASE quality_status
        WHEN 'accepted' THEN 'Принята'
        WHEN 'inspection' THEN 'На проверке'
        WHEN 'rejected' THEN 'Отклонена'
    END AS quality_description
FROM deliveries
ORDER BY delivery_id;
