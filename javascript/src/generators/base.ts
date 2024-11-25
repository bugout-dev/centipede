import { parse } from "@babel/parser";
import generate from "@babel/generator";
import {FunctionDeclaration} from "@babel/types"
import { type } from "os";

const code = `
function transfer(from, to) {
    
}
`;

const ast = parse(code);

console.log((ast.program.body[0] as FunctionDeclaration))

function make_function(func_name : string, args : String[], body: Object | null) {
    
    let function_def = {
        // start: null,
        // end: null,
        // leadingComments: null,
        // trailingComments: null,
        // innerComments: null,
        // loc: null,
        type: "FunctionDeclaration",
        id: {
            type: "Identifier",
            name: func_name,
        },
        params: args.map((el => {return {
            type: "Identifier",
            name: el
        }})),
        body:  {
            type: "BlockStatement",
            body: body ? [body] : [],

        }
    }
    
    const output = generate(function_def as unknown as FunctionDeclaration, {})
    console.log(output.code)
}


let body = parse('console.log(`Hello ${greeting}`)')

make_function("helloWorld", ["greeting"], body)