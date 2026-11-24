//
//  ApplicationFileList.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import {
    Component,
    Prop,
    Vue,
    toNative
} from 'vue-facing-decorator';
import CloseXIcon from '@components/Icons/CloseX/CloseX.vue';
import { ApplicationFile } from '@models/Application/Application.model';

@Component({
    name: 'ApplicationFileList',
    components: {
        CloseXIcon,
    },
    emits: ['remove'],
})
class ApplicationFileList extends Vue {
    @Prop({ default: () => [] }) files?: Array<ApplicationFile>;
    @Prop({ default: true }) isEditable?: boolean;

    //
    // Methods
    //
    removeFile(file: ApplicationFile): void {
        this.$emit('remove', file);
    }
}

export default toNative(ApplicationFileList);

// export default ApplicationFileList;
