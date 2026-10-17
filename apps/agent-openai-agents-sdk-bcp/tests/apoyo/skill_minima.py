"""Skill mínima de una dimensión sin cobertura, usada para probar que el sistema crece sin tocar el chasis."""

from mrm.contratos.resultado import Evidencia, ResultadoControl, TipoEvidencia, VeredictoControl
from mrm.contratos.skill import ContextoSkill, ResultadoSkill, Skill


class SkillMinimaReferencia(Skill):
    nombre = "revisar-calidad-minima"

    def ejecutar(self, contexto: ContextoSkill) -> ResultadoSkill:
        referencia = contexto.solicitud.referencia.excel
        existe = contexto.ruta(referencia).is_file()
        return ResultadoSkill(
            resultados_control=[
                ResultadoControl(
                    control_id=control.id,
                    nombre=control.nombre,
                    tipo=control.tipo,
                    veredicto=VeredictoControl.CUMPLE if existe else VeredictoControl.NO_CUMPLE,
                    severidad=control.severidad,
                    justificacion="La referencia metodológica está en el expediente" if existe else "Falta la referencia",
                    evidencia=[Evidencia(tipo=TipoEvidencia.ARCHIVO, fuente=referencia, ubicacion="archivo")],
                )
                for control in contexto.controles
            ]
        )
