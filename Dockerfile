FROM public.ecr.aws/lambda/python:3.14
COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt
COPY app/ ${LAMBDA_TASK_ROOT}/app/
CMD ["app.handler.lambda_handler"]
