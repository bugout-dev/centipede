import fs from "fs"
import path from "path"

import { Command } from "commander"

import { generateHardHatInterface } from "./generators/hardhat"
import { MOONWORM_VERSION } from "./version"

async function main() {
    const program = new Command()

    // Handle generate-hardhat command from CLI
    const handleHardHatGenerate = (
        outdir: string,
        name: string,
        projectPath: string
    ) => {
        const workingPath = path.resolve()
        const outdirPath = path.join(workingPath, outdir)

        const buildPath = path.join(projectPath, "artifacts", "contracts")
        const buildFilePath = path.join(
            buildPath,
            `${name}.sol`,
            `${name}.json`
        )

        if (!fs.existsSync(path.resolve(buildFilePath))) {
            console.log(
                `File does not exist: ${buildFilePath}. Maybe you have to compile the smart contracts?`
            )
            process.exit(1)
        }

        const build = JSON.parse(fs.readFileSync(buildFilePath, "utf8"))
        const abi = build["abi"]

        const contractInterface = generateHardHatInterface(abi, name)

        if (!fs.existsSync(outdirPath)) {
            fs.mkdirSync(outdirPath)
        }
        const outdirFilePath = path.join(outdir, `${name}.js`)
        fs.writeFileSync(outdirFilePath, contractInterface)
    }

    try {
        program.version(
            MOONWORM_VERSION,
            "-v, --version",
            "Show moonworm version"
        )

        program
            .command("generate-hardhat")
            .description("Moonworm code generator for hardhat projects")
            .requiredOption(
                "-o, --outdir <directory>",
                "Output directory where files will be generated."
            )
            .requiredOption(
                "-n --name <contract>",
                "Contract name generate interface to"
            )
            .requiredOption(
                "-p --project <path>",
                "Path to brownie project directory"
            )
            .action((options) => {
                handleHardHatGenerate(
                    options.outdir,
                    options.name,
                    options.project
                )
            })

        program.parse()
    } catch (error) {
        console.log("")
        process.exit(1)
    }
}

main()
    .then(() => process.exit(process.exitCode))
    .catch((error) => {
        console.log(error)
        process.exit(1)
    })
