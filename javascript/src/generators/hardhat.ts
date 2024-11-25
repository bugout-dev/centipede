interface input {
    internalType: String
    name: String
    type: String
}
interface abiItem {
    name: string
    inputs: Array<input>
    outputs: Array<String>
    stateMutability: String
    type: String
}

export function generateHardHatInterface(
    abi: Array<abiItem>,
    name: string
): string {
    // return `console.log("${name}")`
    const contractName = name
    const contractInterface = abi.map((abiItem) => {
        console.log("abiItem", abiItem.name)
        if (!abiItem.name) return ""

        const string =
            `${abiItem.name} (address, ${abiItem.inputs.map(
                (inputItem) => inputItem.name
            )}) {
            const Contract = await ethers.getContractFactory("${contractName}");
            const contract = await Contract.attach(` +
            "`${address}`" +
            `);
            await contract.${abiItem.name}(${abiItem.inputs.map(
                (inputItem) => inputItem.name
            )});
        };
        `
        return string
    })
    return `export class Moonworm {
        constructor () {}
        ${contractInterface.join("")}
    };`
}
