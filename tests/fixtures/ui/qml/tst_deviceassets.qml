import QtQuick
import QtTest
import "../../../../app/DeviceAssets.js" as Assets
TestCase {
    name:"DeviceAssets"
    function test_folders_per_model() {
        compare(Assets.candidates("MX Master"),["mx-master"])
        compare(Assets.candidates("MX Master 2S"),["mx-master-2s","mx-master"])
        compare(Assets.candidates("MX Master 3"),["mx-master-3","mx-master-3s"])
        compare(Assets.candidates("MX Master 3S"),["mx-master-3s"])
        compare(Assets.candidates("MX Master 4"),["mx-master-4","mx-master-3s"])
        compare(Assets.candidates("MX Vertical"),["mx-vertical"])
        // Other models only ever try their own folder, never another model's picture.
        compare(Assets.candidates("MX Anywhere 3"),["mx-anywhere-3"])
        compare(Assets.candidates("MX Anywhere 2S"),["mx-anywhere-2s"])
        compare(Assets.candidates("MX Ergo S"),["mx-ergo-s"])
        compare(Assets.candidates("MX Anywhere 3 (fixture)"),["mx-anywhere-3-fixture"])
        compare(Assets.candidates("unknown"),[])
        compare(Assets.candidates(""),[])
        compare(Assets.candidates(undefined),[])
    }
    function test_missing_folders_fall_back() {
        const list=Assets.candidates("MX Master 3")
        // Still checking the model's own folder: wait.
        compare(Assets.choose(list,{}),null)
        compare(Assets.choose(list,{"mx-master-3":false}),null)
        // Own folder first when it has a picture.
        compare(Assets.choose(list,{"mx-master-3":true,"mx-master-3s":true}),"mx-master-3")
        // Then the same-body folder.
        compare(Assets.choose(list,{"mx-master-3":false,"mx-master-3s":true}),"mx-master-3s")
        // Neither has a picture (for example the 3S render is not added yet): silhouette.
        compare(Assets.choose(list,{"mx-master-3":false,"mx-master-3s":false}),"")
        compare(Assets.choose(Assets.candidates("MX Vertical"),{"mx-vertical":false}),"")
        compare(Assets.choose(Assets.candidates("MX Ergo"),{"mx-ergo":false}),"")
        compare(Assets.choose([],{}),"")
    }
    function test_missing_preferred_folder_keeps_probing() {
        const master=Assets.candidates("MX Master 2S")
        // A complete family fallback is shown, but the 2S folder may still appear.
        verify(Assets.preferredMissing(master,"mx-master"))
        const three=Assets.candidates("MX Master 3")
        verify(Assets.preferredMissing(three,"mx-master-3s"))
        // Silhouette shown, or still checking: keep probing.
        verify(Assets.preferredMissing(three,""))
        verify(Assets.preferredMissing(three,null))
        // The model's own folder is shown: nothing better can appear.
        verify(!Assets.preferredMissing(three,"mx-master-3"))
        verify(!Assets.preferredMissing(Assets.candidates("MX Master"),"mx-master"))
        verify(!Assets.preferredMissing(Assets.candidates("MX Master 3S"),"mx-master-3s"))
        // An unknown model has no folder to wait for.
        verify(!Assets.preferredMissing([],""))
        // Once the preferred folder gains a picture, choose() switches to it.
        compare(Assets.choose(three,{"mx-master-3":false,"mx-master-3s":true}),"mx-master-3s")
        compare(Assets.choose(three,{"mx-master-3":true,"mx-master-3s":true}),"mx-master-3")
    }
    function test_credit_follows_the_picture() {
        const silhouette=Assets.credit("",{})
        verify(silhouette.text.indexOf("danish_blends") >= 0)
        verify(silhouette.changes.indexOf("silhouette") >= 0)
        const own=Assets.credit("mx-vertical",{credit:"Vertical model by someone",credit_changes:"Relit.",credit_url:"https://example.org/v",license:"CC BY 4.0",license_url:"https://creativecommons.org/licenses/by/4.0/"})
        compare(own.text,"Vertical model by someone")
        compare(own.url,"https://example.org/v")
        compare(own.license,"CC BY 4.0")
        compare(Assets.credit("mx-master-3s",{placeholder:true}).text,"No image credit supplied.")
        compare(Assets.credit("mx-master-3s",{}).license,"CC BY-NC 4.0")
    }
    function test_only_reported_controls_get_hotspots() {
        const points=[{name:"middle"},{name:"thumb_wheel"},{name:"gesture"},{name:"back"}]
        const vertical={buttons:[{name:"middle",available:true},{name:"gesture",available:false},{name:"back",available:true}],thumb_wheel:{available:false}}
        compare(Assets.reported(points,vertical,[]).map(function(p) { return p.name }),["middle","back"])
        compare(Assets.reported(points,vertical,["thumb_wheel"]).map(function(p) { return p.name }),["middle","thumb_wheel","back"])
        // No mouse yet: keep every hotspot.
        compare(Assets.reported(points,null,[]).length,4)
    }
}
