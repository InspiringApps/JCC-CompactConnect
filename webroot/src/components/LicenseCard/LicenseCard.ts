//
//  LicenseCard.ts
//  CompactConnect
//
//  Created by InspiringApps on 10/8/2024.
//
import {
    Component,
    Vue,
    toNative,
    Prop
} from 'vue-facing-decorator';
import { License } from '@/models/License/License.model';
import { State } from '@/models/State/State.model';

@Component({
    name: 'LicenseCard',
})
class LicenseCard extends Vue {
    @Prop({ required: true }) license?: License;

    //
    // Data
    //

    //
    // Lifecycle
    //

    //
    // Computed
    //
    get status():string {
        return 'Active';
    }

    get stateTitle():string {
        return this.$t('licensing.state');
    }

    get state(): State | null {
        return this.license?.issueState || null;
    }

    get stateContent():string {
        return this.state?.name() || '';
    }

    get issuedTitle():string {
        return this.$t('licensing.issued');
    }

    get issuedContent():string {
        return this.license?.issueDateDisplay() || '';
    }

    get expiresTitle():string {
        return this.$t('licensing.expires');
    }

    get expiresContent():string {
        return this.license?.expireDateDisplay() || '';
    }

    get disciplineTitle():string {
        return this.$t('licensing.disciplineStatus');
    }

    get disciplineContent():string {
        return 'No discipline';
    }

    //
    // Methods
    //
}

export default toNative(LicenseCard);

// export default LicenseCard;