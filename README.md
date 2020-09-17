# 🤖pautabot

_Bot_ de Twitter que postea cuando la [Municipalidad de Bahía Blanca](http://bahia.gob.ar) emite una orden de compra de pauta publicitaria

![Tweet de ejemplo](https://raw.githubusercontent.com/jazzido/pautabot/master/example_tweet.png)

## ¿Cómo funciona?

`pautabot` monitorea el [web service de gasto en pauta publicitaria](https://datos.bahia.gob.ar/dataset/publicidad/archivo/36dc9d80-cc4c-46fa-a9e1-5ace789d8a49) que publica la Municipalidad. Si el monto para un proveedor aumentó con respecto a la última vez que corrimos nuestro proceso, detectamos sus nuevas órdenes de compra.

Lamentablemente, el _web service_ mencionado publica el monto total de servicios adquiridos a cada proveedor, por lo que se requiere una consulta al [web service que devuelve _todas_ las órdenes de compra para el ejercicio actual](https://datos.bahia.gob.ar/dataset/f3a0967e-bddd-49d9-a541-d0665e747f6d/archivo/b54b61b2-fbd4-4896-8cce-8141fa0cf259). 

Obtenemos las órdenes de compra para los proveedores que aumentaron el monto y hacemos un último control, que consiste en detectar si la palabra "publicidad" aparece en el detalle de la orden. Esto es necesario porque es posible que se emitan órdenes de compra a proveedores por conceptos distintos a publicidad.
Podríamos evitarnos este malabar si las órdenes de compra incluyeran información sobre la clasificación presupuestaria del gasto. Previsiblemente, la municipalidad no incluyó esa información.

## Cosas para mejorar

El código está bastante complicado porque lo escribí medio de un tirón. Se merece unas reparaciones.

## Licencia

El código de `pautabot` se publica bajo [Licencia MIT](https://es.wikipedia.org/wiki/Licencia_MIT). En pocas palabras, hacé lo que se te cante con el código. Si lo incluís en otro sistema, tenés que incluir el texto de la licencia de `pautabot`.
