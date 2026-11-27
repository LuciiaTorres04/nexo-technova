# Conclusiones: ModeloReglas vs ModeloLLM
## 1. Precisión

Las reglas respondieron bien 7 de 10 preguntas. En las otras 3 (portátil, SSD y HDD, pedido roto) dijeron que no estaban seguras. La IA contestó las 10, pero con fallos: en el horario añadió que se puede dejar un mensaje fuera de horas, algo que no está en los datos de la tienda; en la recomendación del portátil mezcló información sobre la web y los pagos que no se había pedido; y en la conversión estimó unos 110 $ frente a los 108,70 $ de la calculadora, que usa una tasa fija. En el pedido roto actuó bien, porque reconoció que no tenía información. Para datos de la empresa confío más en las reglas.

## 2. Velocidad

Las reglas son mucho más rápidas: tardaron 0,34 ms de media y la IA 468 ms, unas 1.400 veces más. Es porque las reglas se ejecutan en mi ordenador, mientras que la IA está en un servidor de internet y tiene que generar la respuesta palabra a palabra. Aun así, medio segundo es aceptable para un chat.

## 3. Consumo de tokens y coste

Las reglas gastaron 0 tokens y 0 €. La IA gastó 788 tokens de salida y 0,0063 €, unos 79 tokens por pregunta. Con 10.000 preguntas al día serían unos 6,30 € diarios, unos 189 € al mes. Si la IA solo contestara las 3 que las reglas no saben, habrían sido 430 tokens y 0,0034 €: un 45 % menos. La fórmula usada solo cuenta los tokens de salida.

## 4. Facilidad de uso

Con la IA se puede escribir con naturalidad y sobre cualquier tema. Las reglas necesitan que aparezcan ciertas palabras. Añadir una regla exige tocar el código, mientras que cambiar el comportamiento de la IA es editar el texto del prompt, aunque el resultado es menos predecible.


## 5. Robustez

Las reglas funcionan sin internet y responden siempre igual. La IA depende de la conexión, de la clave y de los límites del proveedor, y sus respuestas cambian entre ejecuciones: en una anterior, la recomendación del portátil se cortó al llegar a los 300 tokens y en esta no. Los reintentos con espera exponencial cubren los errores temporales (429 y 5xx). Por eso la mejor solución es la híbrida: reglas para los datos exactos e IA para el resto.

