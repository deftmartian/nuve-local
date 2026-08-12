// Repair one exact imported structure length in a disposable analysis project.
// @category Nuve

import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.Structure;
import java.util.Iterator;

public class RepairStructureLength extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 2) {
            throw new IllegalArgumentException("expected exact data-type path and byte length");
        }
        int requestedLength = Integer.decode(arguments[1]);
        if (requestedLength < 1) {
            throw new IllegalArgumentException("byte length must be positive");
        }

        Iterator<DataType> types = currentProgram.getDataTypeManager().getAllDataTypes();
        int matches = 0;
        while (types.hasNext()) {
            DataType type = types.next();
            if (!type.getPathName().equals(arguments[0]) || !(type instanceof Structure)) {
                continue;
            }
            Structure structure = (Structure) type;
            println("before: " + structure.getPathName() + " length=" + structure.getLength());
            if (structure.getLength() > requestedLength) {
                throw new IllegalArgumentException("refusing to shrink " + structure.getPathName());
            }
            while (structure.getLength() < requestedLength) {
                int beforeLength = structure.getLength();
                structure.growStructure(requestedLength - beforeLength);
                if (structure.getLength() <= beforeLength) {
                    throw new IllegalStateException(
                        "structure did not grow: " + structure.getPathName()
                    );
                }
            }
            println("after: " + structure.getPathName() + " length=" + structure.getLength());
            matches++;
        }
        if (matches != 1) {
            throw new IllegalArgumentException(
                "expected one structure, found " + matches + ": " + arguments[0]
            );
        }
    }
}
