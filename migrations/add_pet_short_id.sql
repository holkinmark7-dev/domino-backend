-- Добавить короткий числовой ID для питомцев
ALTER TABLE pets ADD COLUMN IF NOT EXISTS short_id SERIAL;

-- Создать уникальный индекс
CREATE UNIQUE INDEX IF NOT EXISTS pets_short_id_idx ON pets(short_id);
