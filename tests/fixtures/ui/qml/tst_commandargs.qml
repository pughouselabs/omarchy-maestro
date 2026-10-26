import QtQuick
import QtTest
import "../../../../app/CommandArgs.js" as Args
TestCase {
    name:"CommandArgs"
    function test_shell_quoting() {
        compare(Args.split('notify-send "Hello from Maestro"'),["notify-send","Hello from Maestro"])
        compare(Args.split("program 'single quoted' a\\ b"),["program","single quoted","a b"])
        compare(Args.split('program "literal $HOME" "a\\\\b"'),["program","literal $HOME","a\\b"])
        compare(Args.split('program ""'),["program",""])
        compare(Args.split('["program","JSON argument"]'),["program","JSON argument"])
        const input=["program","a'b",'a"b',"two words","$HOME"]
        compare(Args.split(Args.format(input)),input)
    }
    function test_invalid() {
        let failed=false
        try { Args.split('program "unfinished') } catch(error) { failed=true }
        verify(failed)
        failed=false
        try { Args.split('program \\') } catch(error) { failed=true }
        verify(failed)
    }
}
