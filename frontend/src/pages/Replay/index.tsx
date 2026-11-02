import React, { useContext, useEffect } from "react";
import {
    Row,
} from "antd";

import InfoPanel from "./LeftPanel";
import { RightPanel } from "./ChatBox";
import Deck from "./Deck";
import { useParams } from "react-router";
import { store, StoreContext } from "./store";
import { observer } from 'mobx-react-lite'
import TimelinePlayer from "./TimelinePlayer";

// const IconFont = createFromIconfontCN({
//     scriptUrl: "//at.alicdn.com/t/font_3397267_y3yy0ckhrj.js",
// });

const Replay: React.FC = observer(() => {
    const params = useParams();
    const expID = params.id;

    const store = useContext(StoreContext)

    useEffect(() => {
        store.init(expID)
    }, [expID, store]);

    return (
        <>
            <div className="deck">
                <Deck style={{}} />
            </div>

            <div className="agentsociety-left">
                <InfoPanel />
            </div>
            {/* {(store.globalPrompt ?? "") !== "" &&
                < div className='global-prompt'>
                    <p className='global-prompt-inner'>{store.globalPrompt}</p>
                </div >
            } */}

            <div className='control-progress'>
                <TimelinePlayer initialInterval={1000} />
            </div>
            <Row justify="center" align="middle" style={{
                backgroundColor: "#FFFFFF",
                borderRadius: "0px 0px 16px 16px",
                boxShadow: "0px 4px 10px 0px rgba(80, 80, 80, 0.1)",
            }}>
            </Row>
            <div className="agentsociety-right">
                <RightPanel />
            </div>
        </>
    );
});

const Page = () => {
    return (
        <StoreContext.Provider value={store}>
            <Replay />
        </StoreContext.Provider>
    );
}

export default Page;
