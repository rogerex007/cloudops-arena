"""Shared, fixed progress vocabulary. Never forward participant stdout here."""
STAGES={
    'apply':'Despliegue Terraform y verificación de persistencia',
    'received':'Solicitud recibida', 'source':'Verificación del repositorio y commit',
    'vm':'Inicio del laboratorio aislado', 'policy':'Revisión de recursos y permisos',
    'floci':'Inicio de Floci', 'format':'Formato Terraform',
    'init':'Inicialización de Terraform', 'validate':'Validación de configuración',
    'plan':'Generación del plan', 'review':'Revisión del plan oficial',
    'cleanup':'Limpieza del laboratorio',
    'duplicates':'Duplicados y operaciones únicas', 'partial_batch':'Fallos parciales del lote',
    'failure':'Fallo controlado e independencia de Inventory', 'retries':'Reintentos de SQS',
    'dlq':'Traslado nativo a la DLQ', 'recovery':'Recuperación y nueva entrega',
    'fixtures':'Preparación del flujo de prueba', 'orders':'Recepción y persistencia de órdenes',
    'routing':'Publicación EventBridge y entrega a SQS', 'consumers':'Procesamiento de pagos e inventario',
}
STATUSES={'running','passed','failed'}


def curated(stage,status):
    if stage not in STAGES or status not in STATUSES:
        raise ValueError('Invalid progress event')
    return {'stage':stage,'status':status,'message':STAGES[stage]}
