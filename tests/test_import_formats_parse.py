import datetime, pathlib, sys
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import import_formats as F                              # noqa: E402

assert F.parse_date(13, 8, 2009) == datetime.date(2009, 8, 13)
assert F.parse_date("NA", 8, 2009) is None
assert F.parse_num("2.7") == 2.7 and F.parse_num("NA") is None
assert F.parse_hora("7:30") == "07:30" and F.parse_hora("NA") is None

masivos_headers = list(F.FORMATS["MASIVOS_LEGACY"].header_signature)[:5] + \
    ["ID","Num.Formato","Comunidad/ Sitio de arribo","Lugar/ Sitio de pesca","Nombre comun","Captura (kg)"]
assert F.detect_format(["ID","Num.Formato","Tecnico","Dia ","Mes ","Año",
                        "Comunidad/ Sitio de arribo","Lugar/ Sitio de pesca","Nombre comun",
                        "Captura (kg)","Otros gastos"]) in ("MASIVOS_LEGACY","BITACORA_LEGACY")

rows = F.parse_rows(["Dia ", "Nombre comun", "Captura (kg)"],
                    [(13, "Cochito", 50), ("NA", "NA", "NA")])
assert rows == [{"Dia": 13, "Nombre comun": "Cochito", "Captura (kg)": 50}]   # all-NA row dropped, headers stripped
print("TODOS LOS CHECKS PASAN")
