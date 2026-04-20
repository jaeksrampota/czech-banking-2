# Loga společností

Sem se ukládají loga bank a institucí ve formátu **SVG** nebo **PNG**, pojmenovaná podle jejich `id`
z `config/competitors/<id>.yaml` — např. `ceska_sporitelna.svg`, `kb.svg`.

`CompanyLogo.tsx` se nejdřív pokusí načíst `/logos/<id>.svg`; pokud soubor neexistuje,
zobrazí se fallback (kolečko s iniciálou obarvené podle tieru).

## Placeholdery v tomto repu

V repu jsou jednoduché SVG placeholdery (2písmenný monogram v kroužku obarveném podle tieru
— T1 červená, T2 modrá, T3 šedá). Nejsou to skutečná loga bank; slouží jen k demonstraci toho,
že UI zobrazí reálný obrázek, pokud soubor existuje.

Pro nahrazení reálnými logy:
- přetáhněte SVG/PNG na `<id>.svg` (resp. `.png` a upravte `CompanyLogo.tsx`)
- ideální rozměry: 64×64 px, pozadí transparentní nebo bílé, safezone cca 8 px
