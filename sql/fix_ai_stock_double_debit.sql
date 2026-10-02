CREATE OR REPLACE FUNCTION public.aggiorna_giacenza_da_movimento()
RETURNS trigger LANGUAGE plpgsql
AS $fn$
BEGIN
    -- This RPC has already debited the matched stock row under its original
    -- code/origin. Its movement is an audit record, not a second stock debit.
    IF NEW.tipo_movimento = 'SCARICO'
       AND NEW.origine = 'SCARICO SALA AI'
       AND NEW.riferimento_tipo = 'INTERVENTO'
       AND NEW.note = 'Scarico sala AI flessibile'
    THEN
        RETURN NEW;
    END IF;
    INSERT INTO public.giacenze(
        codice_magazzino, codice, lotto, scadenza, quantita, origine, updated_at)
    VALUES (
        NEW.codice_magazzino, NEW.codice, NEW.lotto, NEW.scadenza,
        NEW.quantita, NEW.origine, now())
    ON CONFLICT (codice_magazzino, codice, lotto, origine)
    DO UPDATE SET
        quantita = giacenze.quantita + excluded.quantita,
        scadenza = coalesce(excluded.scadenza, giacenze.scadenza),
        updated_at = now();
    RETURN NEW;
END;
$fn$;
