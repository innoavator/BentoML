template1 = """
from fastapi import FastAPI
from {path} import {class_name}
import uvicorn

app = FastAPI()
file = r"{file_path}"

{func_name}={class_name}()

@app.get("/")
def hello_world():
    msg="Welcome to my FastAPI project!"\
        "Please visit the /docs to see the API documentation."
    return msg\n
    """
template2 = """
# WARNING:DO NOT EDIT THE BELOW LINE
app.add_api_route(
        path="/{route_path}",
        endpoint={endpoint},
        methods={http_methods},
    )\n
        """
template3 = """
if __name__ == "__main__":
    {func_name}.artifacts.load_all(file)
    uvicorn.run(
            app=app,
            host='0.0.0.0',
            port=8080
        )\n"""


def create_fastapi_file(class_name, module_name, apis_list, store_path):
    import os
    path = f"{class_name}.{module_name}"
    file_path = os.path.join(f"{class_name}","artifacts")
    func_name = class_name.lower() + "_func"
    complete_template = template1.format(
        path=path,
        class_name=class_name,
        file_path=file_path,
        func_name=func_name
    )

    for api in apis_list:
        complete_template += template2.format(
            route_path=api.route,
            endpoint=f"{func_name}.{api.name}",
            http_methods=api.http_methods
        )

    complete_template += template3.format(
        func_name=func_name
    )

    try:
        with open(store_path, "x") as f:
            f.write(complete_template)
    except FileExistsError:
        raise Exception("The FastAPI file already exists")